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
  access 'auto'
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
