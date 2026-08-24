# Hour roll 496541 + Iceberg 496540 (05:13Z)

Sampler still C++ (`pid 2989721`). At 05:00 UTC `gpu_kudu_create` no-op’d
(`exists`) so hour **496541** had no range tablet (`NonCoveredRange`).
HS2 `ALTER TABLE … ADD IF NOT EXISTS RANGE PARTITION` added
496541–496544. C++ jsonl upsert 78726; FDW `496541` lag ~0.

Closed hour **496540** analog: 19968 jsonl rows →
`gpu_metrics_hour_496540.h5` (197495 B) on analog + Iceberg data
prefixes. Polarisfork append `FileFormat.HDF5`. HS2
`gpu_metrics_tier1` GROUP BY = 12156+21930+21594+**19968**. Sample
`power_w=109` `util=100` `mem=21334` (real nvidia-smi).

`gpu_kudu_create.cc` now `AddRangePartition` when the table exists.
`IcebergHdf5Register` sets Hadoop `fs.s3.impl=S3AFileSystem` so
`s3://` metadata commits.

Do not DROP Kudu 496540: FDW strip is still `kudu_scan` of tier0.
UNION view double-counts that hour (34675 Kudu + 19968 Iceberg).
Strip=1h `driver=warehouse` matrix 72000.
