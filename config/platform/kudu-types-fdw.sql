-- Foreign table covering every Kudu scalar + 1D INT64 ARRAY.
-- Table is created by scripts/kudu_types_probe.cc
--   kudu_table = impala::signals_dataproducts.kudu_types_probe

CREATE SERVER IF NOT EXISTS impala_kudu_srv
  FOREIGN DATA WRAPPER impala_fdw
  OPTIONS (
    host 'tinybox.dev.vista.zndx.org',
    port '21050',
    auth 'kerberos',
    kudu_masters 'tinybox.dev.vista.zndx.org:7051',
    default_access 'auto'
  );

CREATE USER MAPPING IF NOT EXISTS FOR CURRENT_USER SERVER impala_kudu_srv
  OPTIONS (
    principal 'signals@DEV.VISTA.ZNDX.ORG',
    keytab '/home/rch/local/src/wxs/signals/.devenv/kdc/signals.keytab'
  );

DROP FOREIGN TABLE IF EXISTS kudu_types_probe CASCADE;
CREATE FOREIGN TABLE kudu_types_probe (
  id integer,
  c_bool boolean,
  c_i8 smallint,
  c_i16 smallint,
  c_i32 integer,
  c_i64 bigint,
  c_f real,
  c_d double precision,
  c_str text,
  c_bin bytea,
  c_ts timestamptz,
  c_date date,
  c_dec numeric,
  c_vc varchar(16),
  c_arr bigint[]
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'kudu_types_probe',
  kudu_table 'impala::signals_dataproducts.kudu_types_probe',
  access 'kudu_scan'
);
