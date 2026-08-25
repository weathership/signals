-- Settled extended DCGM fields — Iceberg tier1, HDF5 analog on RustFS.
-- Same grain as gpu_dcgm_tier0 so UNION ALL is schema-identical.
--
-- Impala's CREATE ... STORED AS ICEBERG does not reach the Polaris
-- MetaProvider in this HMS-free catalog; the table is created through the
-- Iceberg REST API and registered in signals_catalog.catalog_tables with
-- table_type ICEBERG. This file records the intended shape.
--
--   POST /api/catalog/v1/signals/namespaces/signals_dataproducts/tables
--   INSERT INTO catalog_tables (db_name, table_name, table_type, parameters)
--
-- Schema: epoch_hour INT, ts_ns BIGINT, gpu_index INT, field STRING, value DOUBLE
-- Partition: identity(epoch_hour);  write.format.default = hdf5

CREATE VIEW IF NOT EXISTS signals_dataproducts.gpu_dcgm AS
SELECT epoch_hour, ts_ns, gpu_index, field, value
  FROM signals_dataproducts.gpu_dcgm_tier0
UNION ALL
SELECT epoch_hour, ts_ns, gpu_index, field, value
  FROM signals_dataproducts.gpu_dcgm_tier1 t1
 WHERE t1.epoch_hour NOT IN (
   SELECT epoch_hour FROM signals_dataproducts.gpu_dcgm_tier0 GROUP BY 1
 );
