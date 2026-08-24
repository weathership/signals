-- Foreign tables: devenv Postgres :5455 → impala_fdw → Impala HS2
--   gpu_metrics_tier0  Kudu (access auto — kudu_scan when the shape is closed)
--   gpu_metrics_tier1  Iceberg+HDF5 (always impala_sql)
--   gpu_metrics        Impala UNION view (always impala_sql)
--
-- Transparent hierarchy: clients SELECT FROM gpu_metrics; they do not choose
-- a store. Iceberg FTs must not use kudu_scan (SPEC lift: Iceberg ⇒ HS2).

CREATE SERVER IF NOT EXISTS impala_kudu_srv
  FOREIGN DATA WRAPPER impala_fdw
  OPTIONS (
    host 'tinybox.dev.vista.zndx.org',
    port '21050',
    auth 'kerberos',
    kudu_masters 'tinybox.dev.vista.zndx.org:7051',
    default_access 'auto'
  );

ALTER SERVER impala_kudu_srv OPTIONS (
  SET host 'tinybox.dev.vista.zndx.org',
  SET auth 'kerberos',
  SET kudu_masters 'tinybox.dev.vista.zndx.org:7051'
);

-- USER MAPPING: Impala Java SASL is still KUDU-2121; kudu_scan uses the
-- C++ client + this keytab. Mapping for the lab role and CURRENT_USER.
CREATE USER MAPPING IF NOT EXISTS FOR CURRENT_USER SERVER impala_kudu_srv
  OPTIONS (
    principal 'signals@DEV.VISTA.ZNDX.ORG',
    keytab '/home/rch/local/src/wxs/signals/.devenv/kdc/signals.keytab'
  );
CREATE USER MAPPING IF NOT EXISTS FOR signals SERVER impala_kudu_srv
  OPTIONS (
    principal 'signals@DEV.VISTA.ZNDX.ORG',
    keytab '/home/rch/local/src/wxs/signals/.devenv/kdc/signals.keytab'
  );

DROP FOREIGN TABLE IF EXISTS gpu_metrics_tier0 CASCADE;
CREATE FOREIGN TABLE gpu_metrics_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  power_w real,
  util_pct real,
  mem_used_mb real,
  temp_c real
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'gpu_metrics_tier0',
  kudu_table 'impala::signals_dataproducts.gpu_metrics_tier0',
  access 'kudu_scan'
);

DROP FOREIGN TABLE IF EXISTS gpu_metrics_tier1 CASCADE;
CREATE FOREIGN TABLE gpu_metrics_tier1 (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  power_w real,
  util_pct real,
  mem_used_mb real,
  temp_c real
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'gpu_metrics_tier1',
  access 'impala_sql'
);

-- Logical hierarchy is the Impala UNION view (Kudu hours still present;
-- Iceberg fills the rest). Do not recreate that UNION as a Postgres VIEW
-- of kudu_scan ∪ impala_sql: the Iceberg foreign scan then projects only
-- epoch_hour (the NOT IN filter column) and measure columns come back NULL.
-- Writes stay on gpu_metrics_tier0 (kudu_scan / G11).
DROP VIEW IF EXISTS gpu_metrics CASCADE;
DROP FOREIGN TABLE IF EXISTS gpu_metrics CASCADE;
CREATE FOREIGN TABLE gpu_metrics (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  power_w real,
  util_pct real,
  mem_used_mb real,
  temp_c real
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'gpu_metrics',
  access 'impala_sql'
);
