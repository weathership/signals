-- Nautilus data product — tier0 (Kudu, hot). Governed Data Product of every
-- project's Operations Backlog (signals-protocol zndx.supervision.v1;
-- Nautilus writes these through the project's Postgres impala_fdw transport
-- after journaling to nisshi on RustFS).
--
-- Time grain = UTC hour (epoch_hour = unix_seconds // 3600); range unit = DAY
-- (24 hours per tablet range, the shape signal_tier0 uses). Nautilus keeps
-- [today, today+2d) present itself via impala_fdw_exec ADD RANGE PARTITION,
-- so only the first days are declared here. The catch-all VALUES < first day
-- receives replayed events older than the first boot.
--
-- Column lists are generated from the crate's single source
-- (nautilus/src/store/ddl.rs; `nautilus ddl --fdw` prints the Postgres side).
-- INT8 slots ride as TINYINT and appear as smallint through kudu_scan.
-- `trigger`, `scope` and `position` are Impala reserved words, hence
-- trigger_name / scope_name / position_json.
--
-- Plain scalar shapes: the HS2 `CREATE … STORED AS KUDU` path is fine here
-- (the signals_kudu_create.cc detour exists for signal_tier0's array/decimal
-- shape only) and catalogd auto-registers these rows in catalog_tables.
--
-- tier1 (Iceberg) is PENDING with the in-fork Impala Iceberg row-table write
-- path; until it lands the logical names below are tier0-only views and no
-- day-drop runs for these tables (the Backlog window is 34 h).

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

CREATE TABLE IF NOT EXISTS signals_dataproducts.nautilus_backlog_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  project STRING,
  workflow STRING,
  item_key STRING,
  slot TINYINT,
  state STRING,
  category STRING,
  first_miss_ns BIGINT,
  horizon_slot TINYINT,
  horizon_ns BIGINT,
  escalation_level TINYINT,
  resolved BOOLEAN,
  evidence STRING,
  spec_version STRING,
  engine_build STRING,
  PRIMARY KEY (epoch_hour, ts_ns, project, workflow, item_key, slot)
)
PARTITION BY HASH (workflow) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 496800,
  PARTITION 496800 <= VALUES < 496824,
  PARTITION 496824 <= VALUES < 496848,
  PARTITION 496848 <= VALUES < 496872
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.range_unit' = 'day',
  'signals.product' = 'nautilus',
  'signals.writer' = 'nautilus (impala_fdw kudu_scan via project Postgres)'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.nautilus_events_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  project STRING,
  event_id STRING,
  kind STRING,
  trigger_name STRING,
  scope_name STRING,
  signature STRING,
  observer STRING,
  call_site STRING,
  proposition STRING,
  verdict STRING,
  p FLOAT,
  side_effect STRING,
  task_class STRING,
  task_id BIGINT,
  position_json STRING,
  directive_id STRING,
  forecast_id STRING,
  outcome_known BOOLEAN,
  outcome BOOLEAN,
  tier STRING,
  detail STRING,
  evidence STRING,
  spec_version STRING,
  engine_build STRING,
  PRIMARY KEY (epoch_hour, ts_ns, project, event_id)
)
PARTITION BY HASH (event_id) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 496800,
  PARTITION 496800 <= VALUES < 496824,
  PARTITION 496824 <= VALUES < 496848,
  PARTITION 496848 <= VALUES < 496872
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.range_unit' = 'day',
  'signals.product' = 'nautilus',
  'signals.writer' = 'nautilus (impala_fdw kudu_scan via project Postgres)'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.nautilus_positions_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  project STRING,
  process STRING,
  kind STRING,
  machine STRING,
  phase STRING,
  run_id STRING,
  step STRING,
  momentum BIGINT,
  source STRING,
  health STRING,
  silence_s INT,
  detail STRING,
  PRIMARY KEY (epoch_hour, ts_ns, project, process)
)
PARTITION BY HASH (process) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 496800,
  PARTITION 496800 <= VALUES < 496824,
  PARTITION 496824 <= VALUES < 496848,
  PARTITION 496848 <= VALUES < 496872
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.range_unit' = 'day',
  'signals.product' = 'nautilus',
  'signals.writer' = 'nautilus (impala_fdw kudu_scan via project Postgres)'
);

-- Logical names. tier0-only until nautilus_*_tier1 (Iceberg) exists; then each
-- becomes the union masked by tier0 hours, exactly as signals_dataproducts.signal.
CREATE VIEW IF NOT EXISTS signals_dataproducts.nautilus_backlog AS
SELECT * FROM signals_dataproducts.nautilus_backlog_tier0;
CREATE VIEW IF NOT EXISTS signals_dataproducts.nautilus_events AS
SELECT * FROM signals_dataproducts.nautilus_events_tier0;
CREATE VIEW IF NOT EXISTS signals_dataproducts.nautilus_positions AS
SELECT * FROM signals_dataproducts.nautilus_positions_tier0;
