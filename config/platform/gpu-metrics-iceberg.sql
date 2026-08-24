-- Settled GPU / machine metrics — Iceberg tier1, HDF5 analog files on RustFS.
-- Same grain as gpu_metrics_tier0 so UNION ALL is schema-identical.
-- Requires Impala rebuilt against Iceberg 1.11.0-signals-hdf5 (FileFormat.HDF5).

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

CREATE TABLE IF NOT EXISTS signals_dataproducts.gpu_metrics_tier1 (
  epoch_hour INT,
  ts_ns BIGINT,
  gpu_index INT,
  power_w FLOAT,
  util_pct FLOAT,
  mem_used_mb FLOAT,
  temp_c FLOAT
)
PARTITIONED BY SPEC (epoch_hour)
STORED AS ICEBERG
TBLPROPERTIES (
  'iceberg.catalog' = 'polaris',
  'signals.tier' = '1',
  'write.format.default' = 'hdf5',
  'write.location' = 's3a://signals-dataproducts/iceberg/gpu_metrics_tier1'
);

-- Kudu is authoritative for any hour still present. Iceberg fills the rest
-- so analog-before-DROP cannot double-count under UNION ALL.
-- Impala has no CREATE OR REPLACE VIEW; live updates use ALTER VIEW … AS.
CREATE VIEW IF NOT EXISTS signals_dataproducts.gpu_metrics AS
SELECT epoch_hour, ts_ns, gpu_index, power_w, util_pct, mem_used_mb, temp_c
  FROM signals_dataproducts.gpu_metrics_tier0
UNION ALL
SELECT epoch_hour, ts_ns, gpu_index, power_w, util_pct, mem_used_mb, temp_c
  FROM signals_dataproducts.gpu_metrics_tier1 t1
 WHERE t1.epoch_hour NOT IN (
   SELECT epoch_hour FROM signals_dataproducts.gpu_metrics_tier0 GROUP BY 1
 );
