-- Foreign tables over ranger.* Kudu projections (Postgres :5455/signals)
-- Requires: impala_fdw, Kerberos HS2, tables seeded via just ranger-kudu-projections-seed

-- Reuse atlas server if present; create if missing (same HS2/Kudu masters).
CREATE SERVER IF NOT EXISTS impala_kudu_srv
  FOREIGN DATA WRAPPER impala_fdw
  OPTIONS (
    host 'tinybox.dev.vista.zndx.org',
    port '21050',
    auth 'kerberos',
    kudu_masters 'tinybox.dev.vista.zndx.org:7051',
    default_access 'auto'
  );

DROP FOREIGN TABLE IF EXISTS ranger_tag_resource CASCADE;
CREATE FOREIGN TABLE ranger_tag_resource (
  tag_name text,
  resource_id text,
  resource_type text,
  service_name text,
  owner_guid text,
  updated_ts bigint
) SERVER impala_kudu_srv
OPTIONS (database 'ranger', "table" 'tag_resource', access 'auto');

DROP FOREIGN TABLE IF EXISTS ranger_resource_tag CASCADE;
CREATE FOREIGN TABLE ranger_resource_tag (
  resource_id text,
  resource_type text,
  tag_name text,
  service_name text,
  updated_ts bigint
) SERVER impala_kudu_srv
OPTIONS (database 'ranger', "table" 'resource_tag', access 'auto');

DROP FOREIGN TABLE IF EXISTS ranger_policy_resource_index CASCADE;
CREATE FOREIGN TABLE ranger_policy_resource_index (
  policy_id bigint,
  service_name text,
  resource_signature text,
  access_type text,
  is_allowed boolean,
  updated_ts bigint
) SERVER impala_kudu_srv
OPTIONS (database 'ranger', "table" 'policy_resource_index', access 'auto');
