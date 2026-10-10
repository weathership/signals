# Semantica tier0 tables

`signals_kudu_create` now builds four current-state tables, hashed on `graph_id` (4 buckets, no range):

- `semantica_node_tier0`
- `semantica_edge_tier0`
- `semantica_provenance_tier0`
- `semantica_chunk_tier0`

`impala_fdw_exec` refuses `CREATE TABLE` (`#SL.00000029.RANGEDDL`), so this is the apply path. `catalog_tables` on `signals_catalog` (`:5455`) carries the KUDU rows. Iceberg settle is not registered.

`removed` is INT8 (0 live, 1 tombstone). A boolean NOT is not a predicate `kudu_scan` can push, and the FDW has no DELETE. Created on the lab master at `tinybox.dev.vista.zndx.org:7051`.
