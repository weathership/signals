# Plan: impala_fdw direct Kudu (`kudu_scan`)

**Binding design:** `components/impala_fdw/docs/kudu_scan.md`  
**Trigger:** Frontier harness ~2.5s/hop HS2 floor with correct IN pushdown (214711).

## Why now

Batch size does not help; deparse works. Pull `libkudu_client` before more HS2 pooling for Atlas adjacency.

## PR sequence

| PR | Scope | Exit |
|----|--------|------|
| **K0** | Link `libkudu_client` in FDW/devenv build | `.so` loads |
| **K1** | OpenTable + scan + projection | Full-table SELECT via kudu_scan |
| **K2** | Eq + IN + null predicates; hex32 + binary | Equivalence vs HS2 |
| **K3** | auto promote + fallback + LIMIT | Default edge hop uses kudu_scan |
| **K4** | Re-run frontier bench; publish before/after | hop1 **≪ 100ms** |
| **K5** | Kerberos (later) | S3 identity |

## Not in this track

- FDW DML, TC table, HS2 pool as primary fix, AGE changes

## First code touchpoints

- `Makefile` + `devenv.nix` `impala-fdw:build`
- `src/exec_kudu.{h,cpp}` (new)
- `impala_fdw.c` Begin/Iterate/End/Explain branch
- `path_select.c` stop silent demote to HS2
- `scripts/atlas_frontier_bench.py` optional force path

## Acceptance

1. EXPLAIN on `atlas_edge_out` hop shows `AccessMethod: kudu_scan`
2. Bench hop_ms improved ≥10× vs HS2 baseline on same machine
3. Row sets match HS2 for seed graph
