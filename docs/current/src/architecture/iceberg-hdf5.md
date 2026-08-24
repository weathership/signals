# Iceberg HDF5 in Signals

Percy (2019) described **transparent hierarchical storage**: Kudu for hot
mutable rows, Impala for SQL, cooler data as files. We keep that model:

| Era | Hot | Cool / archive | SQL |
|-----|-----|----------------|-----|
| 2019 | Kudu | Parquet on HDFS | Impala HS2 |
| Now | Kudu `*_tier0` | **Iceberg + HDF5** on RustFS (`s3://signals-dataproducts/iceberg`) | Impala HS2 |

Working Iceberg tree: **`components/iceberg`** (`rch/asf-iceberg`, `rch/devenv`).
Version: `1.11.0-signals-hdf5` (`version.txt`). `FileFormat.HDF5` (`.h5`).

Impala:

1. `just iceberg-publish` — Iceberg + `org.zndx.semantics:iceberg-hdf5` into `$SIG_MAVEN_REPO`
2. `APACHE_ICEBERG_VERSION=1.11.0-signals-hdf5` in `config/impala/impala-config-local.sh`
3. `impala-iceberg-runtime` shades `iceberg-hdf5` + jhdf
4. `IcebergUtil` static-init calls `Hdf5FormatModels.register()`
5. `TIcebergFileFormat.HDF5` / `THdfsFileFormat.HDF5`; BE `HdfsHdf5Scanner` JNI → `IcebergHdf5Scanner`

Until Impala is rebuilt, DataFusion still reads the analog:

```bash
cargo run -p signals-df -- hdf5 --file crates/signals-df/tests/data/sdg_machine_small.h5
```
