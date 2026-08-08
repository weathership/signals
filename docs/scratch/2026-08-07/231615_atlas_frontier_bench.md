# Atlas frontier batch harness (PR-K4)

nodes=100 fanout=2 depth=4
force_access=None compare=True

## HS2 vs kudu_scan hop1

| batch | hs2_hop1_ms | kudu_hop1_ms | speedup | visited match | kudu method |
|------:|------------:|-------------:|--------:|:-------------:|:------------|
| 8 | 131.628 | 96.603 | 1.36 | Y | kudu_scan |
| 32 | 136.406 | 102.015 | 1.34 | Y | kudu_scan |
| 64 | 136.821 | 85.404 | 1.6 | Y | kudu_scan |
| 256 | 134.282 | 101.245 | 1.33 | Y | kudu_scan |

## Gates (design K4 exit)

- hop1 &lt; 50 ms: **False**
- B=32 hop1 &lt; 100 ms: **False**
- visited match: **True**
- EXPLAIN kudu_scan: **True**
- min speedup hop1: **1.33**
- **PASS: False**


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
