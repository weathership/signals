# gpu_metrics FDW is the Impala UNION view (14:35Z)

Postgres `:5455` `gpu_metrics` is a foreign table
`access=impala_sql` of `signals_dataproducts.gpu_metrics` (HS2
`tier0 UNION ALL tier1` with Kudu hours excluded from Iceberg).

A local Postgres VIEW of `kudu_scan` ∪ Iceberg `impala_sql` made the
Iceberg foreign scan project only `epoch_hour` (the `NOT IN` filter
column). `ts_ns`/`gpu_index`/`power_w` came back NULL. Gaius Strip=1h
then crashed in `int(ts_ns)`.

`config/platform/gpu-metrics-fdw.sql` now `CREATE FOREIGN TABLE
gpu_metrics … access=impala_sql`. Writes stay on `gpu_metrics_tier0`
(`kudu_scan`). Applied live; Iceberg hour 496549 returns
`power_w=100` `util=100` `mem=21334`.
