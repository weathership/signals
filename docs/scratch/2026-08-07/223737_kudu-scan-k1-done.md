# PR-K1 complete: kudu_scan OpenTable + projection + safety gate

**Date:** 2026-08-07  
**Design:** `components/impala_fdw/docs/kudu_scan.md` rev 0.2.1

## Landed

- `src/exec_kudu.cpp` — real OpenTable, process client cache, OpenTable success cache,
  `KuduScanner` + `SetProjectedColumnNames` + `SetLimit` + `READ_LATEST` + 60s timeout,
  NextBatch materialize (STRING/BINARY/`\x`hex/INT*/BOOL), refcounted close
- `src/impala_fdw.c` — Begin/Iterate/End/ReScan/Explain kudu branch; resolve
  `kudu_masters` / `kudu_table` (`impala::db.table`); `kudu_column`; parallel_unsafe;
  **KD17** refuse kudu when `remote_exprs != NIL` (forced ERROR / auto LOG→HS2);
  auto open failure → one HS2 fallback + WARNING
- `devenv.nix` install server option `kudu_masters '127.0.0.1:7051'`

## Smoke (devenv)

```
EXPLAIN … atlas_entity_flat LIMIT 5  → AccessMethod: kudu_scan
  KuduTable: impala::atlas.entity_flat
SELECT type_name, name … LIMIT 5     → hive_table | fdw_smoke  (via kudu)
WHERE name='x' + access=kudu_scan    → ERROR PR-K2 predicates not available
access=impala_sql SELECT             → still works
```

## Next

**PR-K2** — typed predicate compile (eq/IN/null), hex32 edges, equivalence vs HS2
