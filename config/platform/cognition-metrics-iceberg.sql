-- Settled cognition metrics — Iceberg tier1, HDF5 analog on RustFS.
-- Same grain as cognition_metrics_tier0 so UNION ALL is schema-identical.

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

CREATE TABLE IF NOT EXISTS signals_dataproducts.cognition_metrics_tier1 (
  epoch_hour INT,
  ts_ns BIGINT,
  channel STRING,
  value DOUBLE,
  present BOOLEAN
)
PARTITIONED BY SPEC (epoch_hour)
STORED AS ICEBERG
TBLPROPERTIES (
  'iceberg.catalog' = 'polaris',
  'signals.tier' = '1',
  'write.format.default' = 'hdf5',
  'write.location' = 's3a://signals-dataproducts/iceberg/cognition_metrics_tier1'
);

-- Kudu is authoritative for any hour still present; Iceberg fills the rest so
-- an analog written before DROP cannot double-count under UNION ALL.
CREATE VIEW IF NOT EXISTS signals_dataproducts.cognition_metrics AS
SELECT epoch_hour, ts_ns, channel, value, present
  FROM signals_dataproducts.cognition_metrics_tier0
UNION ALL
SELECT epoch_hour, ts_ns, channel, value, present
  FROM signals_dataproducts.cognition_metrics_tier1 t1
 WHERE t1.epoch_hour NOT IN (
   SELECT epoch_hour FROM signals_dataproducts.cognition_metrics_tier0 GROUP BY 1
 );
