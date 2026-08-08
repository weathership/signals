# Atlas frontier batch harness (PR-K4)

nodes=100 fanout=2 depth=4
force_access=None compare=True

## HS2 vs kudu_scan hop1

| batch | hs2_exec_ms | kudu_exec_ms | speedup | B-hop kudu_ms | visited | method |
|------:|------------:|-------------:|--------:|--------------:|:-------:|:-------|
| 8 | 68.165 | 33.114 | 2.06 | 29.567 | Y | kudu_scan |
| 32 | 70.471 | 33.902 | 2.08 | 29.952 | Y | kudu_scan |
| 64 | 68.373 | 28.709 | 2.38 | 29.011 | Y | kudu_scan |
| 256 | 65.43 | 30.023 | 2.18 | 28.6 | Y | kudu_scan |

## Gates (design K4 exit — backend Execution Time)

- metric: EXPLAIN ANALYZE Execution Time (hop1_exec) + hop exec_ms_sum for B
- hop1 exec &lt; 50 ms: **True**
- B=32 hop exec &lt; 100 ms: **True**
- visited match: **True**
- EXPLAIN kudu_scan: **True**
- min speedup hop1: **2.06**
- 10× when HS2≥500ms: **None**
- **PASS: True**


## EXPLAIN (batch=8, ANY)
```
                                                  QUERY PLAN                                                   
---------------------------------------------------------------------------------------------------------------
 Foreign Scan on public.atlas_edge_out
   Output: dst
   Impala ShapeId: gov.filtered_scan
   Impala AccessMethod: kudu_scan
   Impala AccessOption: kudu_scan
   Impala KuduMasters: 127.0.0.1:7051
   Impala KuduTable: impala::atlas.edge_out
   Impala KuduNote: projection + remote predicates (kudu_scan)
   Impala Remote SQL: SELECT `dst` FROM `atlas`.`edge_out` WHERE `src` IN ('00000000000000000000000000000000')
(9 rows)


```

## Notes
- READ_LATEST; freeze seed (no concurrent UPSERT during compare).
- Procedural frontier over FDW; AGE remains SoR for topology.
