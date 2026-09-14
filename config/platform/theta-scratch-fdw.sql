-- gaius.theta.cycle — Postgres foreign tables over scratch THS (Kudu tier0 +
-- Impala logical views). Apply to signals :5455 AND gaius :5444; impala_kudu_srv
-- must exist. SoR for DDL: config/platform/theta-scratch-kudu.sql.
--
-- INSERT remainder / incidence into *_tier0 (kudu_scan). Read the views
-- (impala_sql). Expire via Impala DROP RANGE PARTITION, never DELETE FROM.

DROP FOREIGN TABLE IF EXISTS theta_scratch_vertex CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_scratch_vertex_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_scratch_edge CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_scratch_edge_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_scratch_incidence CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_scratch_incidence_tier0 CASCADE;

CREATE FOREIGN TABLE theta_scratch_vertex_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  vertex_id text,
  kind text,
  text_id bigint,
  layer integer,
  feature_idx integer,
  window_start integer,
  window_end integer,
  reason text,
  tau real,
  margin real,
  c_epoch text,
  aperture text,
  hx_generation_id text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'theta_scratch_vertex_tier0',
  kudu_table 'impala::signals_dataproducts.theta_scratch_vertex_tier0',
  access 'kudu_scan');

CREATE FOREIGN TABLE theta_scratch_vertex (
  epoch_hour integer,
  ts_ns bigint,
  vertex_id text,
  kind text,
  text_id bigint,
  layer integer,
  feature_idx integer,
  window_start integer,
  window_end integer,
  reason text,
  tau real,
  margin real,
  c_epoch text,
  aperture text,
  hx_generation_id text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'theta_scratch_vertex',
  access 'impala_sql');

CREATE FOREIGN TABLE theta_scratch_edge_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  edge_id text,
  kind text,
  arity integer,
  c_epoch text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'theta_scratch_edge_tier0',
  kudu_table 'impala::signals_dataproducts.theta_scratch_edge_tier0',
  access 'kudu_scan');

CREATE FOREIGN TABLE theta_scratch_edge (
  epoch_hour integer,
  ts_ns bigint,
  edge_id text,
  kind text,
  arity integer,
  c_epoch text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'theta_scratch_edge',
  access 'impala_sql');

CREATE FOREIGN TABLE theta_scratch_incidence_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  edge_id text,
  vertex_id text,
  vertex_role text,
  pos integer
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'theta_scratch_incidence_tier0',
  kudu_table 'impala::signals_dataproducts.theta_scratch_incidence_tier0',
  access 'kudu_scan');

CREATE FOREIGN TABLE theta_scratch_incidence (
  epoch_hour integer,
  ts_ns bigint,
  edge_id text,
  vertex_id text,
  vertex_role text,
  pos integer
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'theta_scratch_incidence',
  access 'impala_sql');
