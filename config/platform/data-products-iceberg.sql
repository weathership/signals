-- Data-product warehouse — tier1 (Iceberg on RustFS / Polaris).
-- Settled weeks after 4 weeks on Kudu tier0. Do not hour-partition Iceberg
-- (file explosion). details by product; tx/hx by product.
-- pglite: do not CREATE these tables there.

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

CREATE TABLE IF NOT EXISTS signals_dataproducts.tx_tier1 (
  epoch_hour INT,
  product_id STRING,
  tx_id STRING,
  ts_ns BIGINT,
  kind STRING,
  summary STRING,
  source STRING,
  ce_type STRING
)
PARTITIONED BY SPEC (product_id)
STORED AS ICEBERG
TBLPROPERTIES (
  'iceberg.catalog' = 'polaris',
  'signals.tier' = '1',
  'write.location' = 's3a://signals-dataproducts/iceberg/tx_tier1'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.details_tier1 (
  epoch_hour INT,
  e STRING,
  a STRING,
  t STRING,
  v STRING,
  op BOOLEAN,
  ts_ns BIGINT
)
PARTITIONED BY SPEC (e)
STORED AS ICEBERG
TBLPROPERTIES (
  'iceberg.catalog' = 'polaris',
  'signals.tier' = '1',
  'write.location' = 's3a://signals-dataproducts/iceberg/details_tier1'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.hx_exchange_tier1 (
  epoch_hour INT,
  product_id STRING,
  tx_id STRING,
  ts_ns BIGINT,
  agent STRING,
  role STRING,
  message STRING
)
PARTITIONED BY SPEC (product_id)
STORED AS ICEBERG
TBLPROPERTIES (
  'iceberg.catalog' = 'polaris',
  'signals.tier' = '1',
  'write.location' = 's3a://signals-dataproducts/iceberg/hx_exchange_tier1'
);

CREATE TABLE IF NOT EXISTS signals_dataproducts.hx_reasoning_tier1 (
  epoch_hour INT,
  product_id STRING,
  tx_id STRING,
  agent STRING,
  ts_ns BIGINT,
  quality STRING,
  lineage STRING,
  delta STRING,
  trace STRING
)
PARTITIONED BY SPEC (product_id)
STORED AS ICEBERG
TBLPROPERTIES (
  'iceberg.catalog' = 'polaris',
  'signals.tier' = '1',
  'write.location' = 's3a://signals-dataproducts/iceberg/hx_reasoning_tier1'
);
