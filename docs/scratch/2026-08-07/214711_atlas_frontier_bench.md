# Atlas frontier batch harness

nodes=100 fanout=2 depth=4

| batch | total_ms | visited | hop1_ms | hop1 in→out | hop2_ms | pushdown ANY |
|------:|---------:|--------:|--------:|------------:|--------:|:------------:|
| 8 | 7797.267 | 25 | 114.744 | 1→3 | 2581.052 | Y |
| 32 | 10237.099 | 25 | 2547.112 | 1→3 | 2558.378 | Y |
| 64 | 10197.913 | 25 | 2549.853 | 1→3 | 2521.333 | Y |
| 256 | 15426.913 | 25 | 2543.601 | 1→3 | 2558.208 | Y |

## EXPLAIN (batch=8, ANY)
```
                                                  QUERY PLAN                                                   
---------------------------------------------------------------------------------------------------------------
 Foreign Scan on public.atlas_edge_out
   Output: dst
   Impala ShapeId: gov.pk_lookup
   Impala AccessMethod: impala_sql
   Impala AccessOption: impala_sql
   Impala Remote SQL: SELECT `dst` FROM `atlas`.`edge_out` WHERE `src` IN ('00000000000000000000000000000000')
(6 rows)


```

## AGE note
See `213500_apache-age-enhance-opportunities.md` for AGE integrate/enhance list.
Traversal remains procedural SQL over FDW; AGE stays SoR for topology.
