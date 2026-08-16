-- Data-product warehouse — tier0 (Kudu, hot).
-- Time grain = UTC hour. Tablet width = 1 week (168 hours).
-- Settle to tier1 after 4 weeks, then DROP RANGE PARTITION (never row DELETE).
-- https://kudu.apache.org/docs/schema_design.html#range-partition-management
--
-- Hour is the range *unit*; week is the *tablet*. Not a second Kudu range
-- level (Kudu allows one RANGE). Do not HASH on hour (current hour hotspots).
-- t / tx_id is UUIDv7 — identity + datalog order, not the tablet bound.
-- op is BOOLEAN and therefore not in the PK.
--
-- pglite: do not CREATE these tables there.

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

-- Unix epoch hours, week-aligned (hour // 168).
-- 2950*168 = 495600 … 2957*168 = 496776  (~2026-08-07 .. 2026-08-25).
-- ADD a new 168-hour range each week; DROP the range 4 weeks behind
-- after Iceberg verify (same bounds on tx / details / hx).

CREATE TABLE IF NOT EXISTS signals_dataproducts.tx_tier0 (
  epoch_hour INT,
  product_id STRING,
  tx_id STRING,
  ts_ns BIGINT,
  kind STRING,
  summary STRING,
  source STRING,
  ce_type STRING,
  PRIMARY KEY (epoch_hour, product_id, tx_id)
)
PARTITION BY HASH (product_id) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 495600,
  PARTITION 495600 <= VALUES < 495768,
  PARTITION 495768 <= VALUES < 495936,
  PARTITION 495936 <= VALUES < 496104,
  PARTITION 496104 <= VALUES < 496272,
  PARTITION 496272 <= VALUES < 496440,
  PARTITION 496440 <= VALUES < 496608,
  PARTITION 496608 <= VALUES < 496776
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.range_unit' = 'hour',
  'signals.range_width_hours' = '168',
  'signals.settle_weeks' = '4'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.details_tier0 (
  epoch_hour INT,
  e STRING,
  a STRING,
  t STRING,
  v STRING,
  op BOOLEAN,
  ts_ns BIGINT,
  PRIMARY KEY (epoch_hour, e, a, t)
)
PARTITION BY HASH (e) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 495600,
  PARTITION 495600 <= VALUES < 495768,
  PARTITION 495768 <= VALUES < 495936,
  PARTITION 495936 <= VALUES < 496104,
  PARTITION 496104 <= VALUES < 496272,
  PARTITION 496272 <= VALUES < 496440,
  PARTITION 496440 <= VALUES < 496608,
  PARTITION 496608 <= VALUES < 496776
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.range_unit' = 'hour',
  'signals.range_width_hours' = '168',
  'signals.settle_weeks' = '4'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.hx_exchange_tier0 (
  epoch_hour INT,
  product_id STRING,
  tx_id STRING,
  ts_ns BIGINT,
  agent STRING,
  role STRING,
  message STRING,
  PRIMARY KEY (epoch_hour, product_id, tx_id, ts_ns, agent)
)
PARTITION BY HASH (product_id) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 495600,
  PARTITION 495600 <= VALUES < 495768,
  PARTITION 495768 <= VALUES < 495936,
  PARTITION 495936 <= VALUES < 496104,
  PARTITION 496104 <= VALUES < 496272,
  PARTITION 496272 <= VALUES < 496440,
  PARTITION 496440 <= VALUES < 496608,
  PARTITION 496608 <= VALUES < 496776
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.kudu_string_max' = '64KiB',
  'signals.settle_weeks' = '4'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.hx_reasoning_tier0 (
  epoch_hour INT,
  product_id STRING,
  tx_id STRING,
  agent STRING,
  ts_ns BIGINT,
  quality STRING,
  lineage STRING,
  delta STRING,
  trace STRING,
  PRIMARY KEY (epoch_hour, product_id, tx_id, agent)
)
PARTITION BY HASH (product_id) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 495600,
  PARTITION 495600 <= VALUES < 495768,
  PARTITION 495768 <= VALUES < 495936,
  PARTITION 495936 <= VALUES < 496104,
  PARTITION 496104 <= VALUES < 496272,
  PARTITION 496272 <= VALUES < 496440,
  PARTITION 496440 <= VALUES < 496608,
  PARTITION 496608 <= VALUES < 496776
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.kudu_string_max' = '64KiB',
  'signals.settle_weeks' = '4'
);

-- After Iceberg verify for a week whose upper bound is >= 4 weeks old:
--   ALTER TABLE signals_dataproducts.details_tier0
--     DROP RANGE PARTITION 495600 <= VALUES < 495768;
-- Same bounds on tx_tier0 / hx_*_tier0. Never DELETE FROM … WHERE epoch_hour=…
-- Before the next week starts:
--   ALTER TABLE … ADD RANGE PARTITION 496776 <= VALUES < 496944;
