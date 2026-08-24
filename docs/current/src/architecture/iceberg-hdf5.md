# Iceberg HDF5 in Signals

Working Iceberg tree: **`components/iceberg`** (`rch/asf-iceberg`, branch `rch/devenv`).
Do not use `cldr/signals` for this work.

`FileFormat.HDF5` (`.h5`) is on that pin. Impala FE still sets
`APACHE_ICEBERG_VERSION=1.10.1` from Maven Central (`bin/impala-config.sh`).
Warehouse `SELECT` of HDF5 Iceberg data files needs Impala rebuilt against the
submodule (shade `org.zndx.semantics:iceberg-hdf5` into `impala-iceberg-runtime`
and `Hdf5FormatModels.register()`). That is a follow-on.

Until then, Signals DataFusion reads the SysML analog:

```bash
cargo run -p signals-df -- hdf5 --file crates/signals-df/tests/data/sdg_machine_small.h5
```
