-- Gaius FMP warehouse — Impala-visible shape of Kudu tier0.
-- Apply path is scripts/signals_kudu_create.cc (libkudu_client) plus
-- catalog_tables rows in signal-registry.sql. Writers INSERT through
-- Postgres impala_fdw kudu_scan. Do not schema-apply this file over
-- Python impyla; that client is not the THS runtime.
--
-- Grain: one ingest batch row per symbol (profile) or filing/earnings
-- line. Time grain = UTC hour (epoch_hour); range unit = DAY so a closed
-- day can DROP RANGE PARTITION after Iceberg settle (never row DELETE).
-- Catch-all VALUES < 0; the writer ADD RANGE PARTITIONs [today, today+2d).
--
-- tier1 (Iceberg) is PENDING with the in-fork Impala Iceberg row-table
-- write path; until it lands the logical names are tier0-only views.

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

CREATE TABLE IF NOT EXISTS signals_dataproducts.fmp_profile_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  symbol STRING,
  name STRING,
  exchange STRING,
  sector STRING,
  industry STRING,
  market_cap DOUBLE,
  website STRING,
  description STRING,
  PRIMARY KEY (epoch_hour, ts_ns, symbol)
)
PARTITION BY HASH (symbol) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 0
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.range_unit' = 'day',
  'signals.product' = 'gaius.fmp.warehouse',
  'signals.writer' = 'gaius FmpWarehouseFlow (impala_fdw kudu_scan)'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.fmp_filings_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  symbol STRING,
  form STRING,
  filed STRING,
  url STRING,
  PRIMARY KEY (epoch_hour, ts_ns, symbol)
)
PARTITION BY HASH (symbol) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 0
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.range_unit' = 'day',
  'signals.product' = 'gaius.fmp.warehouse',
  'signals.writer' = 'gaius FmpWarehouseFlow (impala_fdw kudu_scan)'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.fmp_earnings_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  symbol STRING,
  announced STRING,
  eps DOUBLE,
  eps_estimated DOUBLE,
  PRIMARY KEY (epoch_hour, ts_ns, symbol)
)
PARTITION BY HASH (symbol) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 0
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.range_unit' = 'day',
  'signals.product' = 'gaius.fmp.warehouse',
  'signals.writer' = 'gaius FmpWarehouseFlow (impala_fdw kudu_scan)'
);

CREATE VIEW IF NOT EXISTS signals_dataproducts.fmp_profile AS
SELECT * FROM signals_dataproducts.fmp_profile_tier0;
CREATE VIEW IF NOT EXISTS signals_dataproducts.fmp_filings AS
SELECT * FROM signals_dataproducts.fmp_filings_tier0;
CREATE VIEW IF NOT EXISTS signals_dataproducts.fmp_earnings AS
SELECT * FROM signals_dataproducts.fmp_earnings_tier0;
