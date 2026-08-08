# Atlas frontier batch harness (PR-K4)

nodes=100 fanout=2 depth=4
force_access=None compare=True

## HS2 vs kudu_scan hop1

| batch | hs2_exec_ms | kudu_exec_ms | speedup | B-hop kudu_ms | visited | method |
|------:|------------:|-------------:|--------:|--------------:|:-------:|:-------|
| 8 | 70.488 | 27.103 | 2.6 | 27.588 | Y | kudu_scan |
| 32 | 68.72 | 27.732 | 2.48 | 30.021 | Y | kudu_scan |

## Gates (design K4 exit — backend Execution Time)

- metric: EXPLAIN ANALYZE Execution Time (hop1_exec) + hop exec_ms_sum for B
- hop1 exec &lt; 50 ms: **True**
- B=32 hop exec &lt; 100 ms: **True**
- visited **set** match: **True**
- per-hop row multiset match: **True**
- all-hops row multiset match: **True**
- equivalence (set+multiset): **True**
- EXPLAIN kudu_scan: **True**
- min speedup hop1: **2.48**
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
