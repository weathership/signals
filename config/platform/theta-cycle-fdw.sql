-- gaius.theta.cycle — product-facing foreign tables.
-- Storage is scratch THS: Kudu tablets remain theta_scratch_*_tier0.
-- Apply to gaius :5444 AND signals :5455; impala_kudu_srv must exist.
-- INSERT *_tier0 (kudu_scan). Read the cycle views (impala_sql).

DROP FOREIGN TABLE IF EXISTS theta_cycle_vertex CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_cycle_vertex_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_cycle_edge CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_cycle_edge_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_cycle_incidence CASCADE;
DROP FOREIGN TABLE IF EXISTS theta_cycle_incidence_tier0 CASCADE;

CREATE FOREIGN TABLE theta_cycle_vertex_tier0 (
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

CREATE FOREIGN TABLE theta_cycle_vertex (
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
  database 'signals_dataproducts', "table" 'theta_cycle_vertex',
  access 'impala_sql');

CREATE FOREIGN TABLE theta_cycle_edge_tier0 (
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

CREATE FOREIGN TABLE theta_cycle_edge (
  epoch_hour integer,
  ts_ns bigint,
  edge_id text,
  kind text,
  arity integer,
  c_epoch text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'theta_cycle_edge',
  access 'impala_sql');

CREATE FOREIGN TABLE theta_cycle_incidence_tier0 (
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

CREATE FOREIGN TABLE theta_cycle_incidence (
  epoch_hour integer,
  ts_ns bigint,
  edge_id text,
  vertex_id text,
  vertex_role text,
  pos integer
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'theta_cycle_incidence',
  access 'impala_sql');
