# GPU metrics soak (04:29Z)

C++ `gpu_kudu_create` / `gpu_kudu_ingest` keep `gpu_metrics_tier0` live.
HS2 Iceberg HDF5 scan of `gpu_metrics_tier1` covers closed hours
496537–496539 (55680 analog rows). Java Kudu SASL still KUDU-2121:
no `gpu_metrics` UNION view. FDW `:5455` `gpu_metrics` is `kudu_scan`.
`gpu_metrics_tier1` `impala_sql` waits on FDW HS2 GSSAPI.

Re-applied `config/platform/gpu-metrics-fdw.sql`. Do not DROP Kudu
range partitions until HS2 can scan tier0.
