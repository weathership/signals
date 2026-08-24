-- Hot GPU / machine metrics — Kudu tier0.
-- Grain: 1 row per GPU per sample. Range unit = UTC hour so a closed hour
-- can DROP RANGE PARTITION after Iceberg+HDF5 verify (never row DELETE).
-- pglite: do not CREATE these tables there.

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

-- Hour bounds are applied by scripts/gpu_metrics_kudu_ingest.py (ADD RANGE
-- for the current UTC hour ± 2). The CREATE below is the schema only; the
-- ingest script issues the RANGE list for the live hour.

CREATE TABLE IF NOT EXISTS signals_dataproducts.gpu_metrics_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  gpu_index INT,
  power_w FLOAT,
  util_pct FLOAT,
  mem_used_mb FLOAT,
  temp_c FLOAT,
  PRIMARY KEY (epoch_hour, ts_ns, gpu_index)
)
PARTITION BY HASH (gpu_index) PARTITIONS 2,
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
  'signals.product' = 'gaius.machine.gpu_metrics'
);
