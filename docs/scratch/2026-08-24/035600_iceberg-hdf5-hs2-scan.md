# HS2 Iceberg HDF5 scan (03:56Z)

`SELECT * FROM signals_dataproducts.gpu_metrics_tier1 LIMIT 2` returns analog
watts/util/mem/temp. `GROUP BY epoch_hour` is 12156+21930.

`impala_fdw` `impala_sql` still cannot GSSAPI to HS2; landing uses `kudu_scan`.
