-- Hot cognition metrics — Kudu tier0. Sibling of gpu_metrics_tier0.
-- Grain: 1 row per channel per sample. Narrow (channel, value) rather than a
-- column per measure: cognition channels change with the model surface, and a
-- narrow table adds one without a warehouse migration.
-- Range unit = UTC hour so a closed hour DROPs whole (never row DELETE).

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

CREATE TABLE IF NOT EXISTS signals_dataproducts.cognition_metrics_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  channel STRING,
  value DOUBLE,
  present BOOLEAN,
  PRIMARY KEY (epoch_hour, ts_ns, channel)
)
PARTITION BY HASH (channel) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 0
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.master_addresses' = 'tinybox.dev.vista.zndx.org:7051',
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.range_unit' = 'hour',
  'signals.range_width_hours' = '1',
  'signals.product' = 'gaius.cognition.metrics'
);
