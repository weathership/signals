# DROP Kudu analog hours 496537–496541 (06:09Z)

Iceberg `gpu_metrics_tier1` holds those hours (496541 = 21594 analog).
Kudu `gpu_metrics_tier0` now only 496542–544 (plus leftover 496536).
Impala UNION `gpu_metrics` matches analog counts + live hour. FDW
`gpu_metrics` `impala_sql` is the client path. Do not re-ADD dropped
ranges.
