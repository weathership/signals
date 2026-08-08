-- Foreign tables over atlas.* Kudu projections (Postgres :5455/signals)
-- Requires: impala_fdw installed, server impala_kudu_srv, tables seeded via HS2.
--
-- BINARY → bytea; BIGINT epoch-micros → bigint (app converts to timestamptz).

-- PR-K4: default_access auto so closed shapes promote to kudu_scan.
-- Per-table access 'auto' (was forced impala_sql until latency/equivalence gates passed).
CREATE SERVER IF NOT EXISTS impala_kudu_srv
  FOREIGN DATA WRAPPER impala_fdw
  OPTIONS (
    host 'tinybox.dev.vista.zndx.org',
    port '21050',
    auth 'kerberos',
    kudu_masters 'tinybox.dev.vista.zndx.org:7051',
    default_access 'auto'
  );

-- entity_flat
DROP FOREIGN TABLE IF EXISTS atlas_entity_flat CASCADE;
CREATE FOREIGN TABLE atlas_entity_flat (
  guid bytea,
  type_name text,
  qualified_name text,
  name text,
  state smallint,
  created_ts bigint,
  updated_ts bigint,
  props_json text
) SERVER impala_kudu_srv
OPTIONS (database 'atlas', "table" 'entity_flat', access 'auto');

-- entity_by_qn
DROP FOREIGN TABLE IF EXISTS atlas_entity_by_qn CASCADE;
CREATE FOREIGN TABLE atlas_entity_by_qn (
  qn_digest bytea,
  guid bytea,
  type_name text
) SERVER impala_kudu_srv
OPTIONS (database 'atlas', "table" 'entity_by_qn', access 'auto');

-- edge_out (hex32 STRING keys — Impala cannot predicate on Kudu BINARY)
DROP FOREIGN TABLE IF EXISTS atlas_edge_out CASCADE;
CREATE FOREIGN TABLE atlas_edge_out (
  src text,
  elabel text,
  dst text,
  dst_type text
) SERVER impala_kudu_srv
OPTIONS (database 'atlas', "table" 'edge_out', access 'auto');

-- edge_in
DROP FOREIGN TABLE IF EXISTS atlas_edge_in CASCADE;
CREATE FOREIGN TABLE atlas_edge_in (
  dst text,
  elabel text,
  src text,
  src_type text
) SERVER impala_kudu_srv
OPTIONS (database 'atlas', "table" 'edge_in', access 'auto');

-- entity_classifications
DROP FOREIGN TABLE IF EXISTS atlas_entity_classifications CASCADE;
CREATE FOREIGN TABLE atlas_entity_classifications (
  tag_name text,
  guid bytea,
  propagate boolean,
  applied_time bigint
) SERVER impala_kudu_srv
OPTIONS (database 'atlas', "table" 'entity_classifications', access 'auto');

-- entity_audit
DROP FOREIGN TABLE IF EXISTS atlas_entity_audit CASCADE;
CREATE FOREIGN TABLE atlas_entity_audit (
  guid bytea,
  event_ts bigint,
  seq bigint,
  event_type text,
  actor text,
  payload_json text
) SERVER impala_kudu_srv
OPTIONS (database 'atlas', "table" 'entity_audit', access 'auto');
