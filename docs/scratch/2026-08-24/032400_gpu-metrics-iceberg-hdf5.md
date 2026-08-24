# GPU metrics Iceberg HDF5 (03:24Z)

Impalad no longer dies on Polarisfork `warehouse` + `iceberg.rest-catalog.warehouse`.
catalogd/impalad restarted with `catalog_config_dir`. HS2 sees
`signals_dataproducts.gpu_metrics_tier0` (Kudu) and `gpu_metrics_tier1`
(Iceberg HDF5, 34086 snapshot rows).

Closed hour 496538 analog is on RustFS and Polarisfork. FDW `:5455`
`gpu_metrics` remains `kudu_scan` (Java Kudu SASL still KUDU-2121).
File scan `SELECT * … LIMIT 3` still NPE in the Iceberg planner; local
`IcebergHdf5Scanner` on the analog `.h5` returns the real 21930 rows.
