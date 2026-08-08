# PR-K2 complete: kudu_scan predicates + HS2 equivalence

**Date:** 2026-08-07  
**Design:** `components/impala_fdw/docs/kudu_scan.md` rev 0.2.3

## Landed

| File | Role |
|------|------|
| `src/kudu_pred.{c,h}` | Compile remote_exprs → `ImpalaKuduPred[]` (OpExpr eq/cmp, ScalarArrayOp IN/ANY, NullTest, AND flatten); `kudu_column`; empty IN → empty_result; IN cap 4096; `<>` refused (no Kudu NOT_EQUAL) |
| `src/exec_kudu.cpp` | `apply_predicates` → Comparison / InList / IsNull / IsNotNull; typed `KuduValue` from PG Oid + schema DataType; empty scan handle (`npreds=-1`) |
| `src/impala_fdw.c` | Begin builds preds; **removed K1 remote_exprs ban**; forced ERROR / auto HS2 fallback on compile/open fail |
| `Makefile` | `kudu_pred.o` when `IMPALA_FDW_WITH_KUDU` |

## Equivalence (devenv, frozen seed)

| Test | HS2 | kudu | multiset_diff |
|------|-----|------|---------------|
| `entity_flat WHERE type_name = 'hive_table'` | 1 | 1 | **0** |
| `edge_out WHERE src = ANY(ARRAY[2 hex32 srcs])` | 6 | 6 | **0** |
| empty `src = ANY(ARRAY[]::text[])` | 0 | 0 | **0** |

EXPLAIN forced kudu + eq shows `AccessMethod: kudu_scan` and remote SQL mirror.

## Latency note (anecdotal)

- entity_flat eq: ~39 ms kudu vs ~78 ms HS2 (single row)
- edge IN hop still needs PR-K3 auto-promote + K4 harness for official ≥10× claim

## Next

**PR-K3** — strict shape recognition (full PK vs HASH allowlist filtered_scan), GUCs, no residual silent demote, residual forced ERROR (KD16)
