-- Foreign tables for the signals warehouse (schema: docs/scratch/2026-08-25/214236_schema-final-e2e.md).
-- Apply to BOTH Postgres instances (signals :5455 and gaius :5444); impala_kudu_srv must exist.
--
--   *_tier0            Kudu, access kudu_scan   (INSERTable; hot tier)
--   signal_tier1       Iceberg+HDF5, impala_sql (settled hours)
--   signal             Impala UNION view, impala_sql — the transparent surface
--   signal_series, clt_feature, clt_label  reference tables (Kudu, never tier)
--
-- Arrays are payload-only: Kudu cannot predicate them. Every filterable
-- dimension is a scalar column.

DROP FOREIGN TABLE IF EXISTS signal CASCADE;
DROP FOREIGN TABLE IF EXISTS signal_tier1 CASCADE;
DROP FOREIGN TABLE IF EXISTS signal_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS signal_series CASCADE;
DROP FOREIGN TABLE IF EXISTS latent_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS clt_feature CASCADE;
DROP FOREIGN TABLE IF EXISTS clt_label CASCADE;
DROP FOREIGN TABLE IF EXISTS clt_activation_tier0 CASCADE;

CREATE FOREIGN TABLE signal_series (
  series_id   bigint,
  name        text,
  vtype       smallint,
  unit        text,
  src         smallint,
  dcgm_field  text,
  description text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'signal_series',
  kudu_table 'impala::signals_dataproducts.signal_series', access 'kudu_scan');

CREATE FOREIGN TABLE signal_tier0 (
  epoch_hour integer,
  ts_ns      bigint,
  series_id  bigint,
  src        smallint,
  gpu        smallint,
  inst       smallint,
  val_i      bigint,
  val_d      numeric(18,6)
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'signal_tier0',
  kudu_table 'impala::signals_dataproducts.signal_tier0', access 'kudu_scan');

CREATE FOREIGN TABLE signal_tier1 (
  epoch_hour integer,
  ts_ns      bigint,
  series_id  bigint,
  src        smallint,
  gpu        smallint,
  inst       smallint,
  val_i      bigint,
  val_d      numeric(18,6)
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'signal_tier1', access 'impala_sql');

-- The hierarchy: Kudu hours ∪ Iceberg hours not still in Kudu. Lives in Impala
-- (catalog_tables VIEW row) so predicates reach both stores through one plan.
CREATE FOREIGN TABLE signal (
  epoch_hour integer,
  ts_ns      bigint,
  series_id  bigint,
  src        smallint,
  gpu        smallint,
  inst       smallint,
  val_i      bigint,
  val_d      numeric(18,6)
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'signal', access 'impala_sql');

CREATE FOREIGN TABLE latent_tier0 (
  epoch_hour integer, ts_ns bigint, stream_id bigint, seq integer,
  kind smallint, step integer, layer smallint, norm real,
  agent text, model text, ref text,
  vec real[], k_vec real[], v_vec real[]
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'latent_tier0',
  kudu_table 'impala::signals_dataproducts.latent_tier0', access 'kudu_scan');

CREATE FOREIGN TABLE clt_feature (
  model_id integer, layer smallint, feature_idx integer,
  top_token_id integer[], top_logit real[], decoder_norm real
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'clt_feature',
  kudu_table 'impala::signals_dataproducts.clt_feature', access 'kudu_scan');

CREATE FOREIGN TABLE clt_label (
  model_id integer, layer smallint, feature_idx integer, valid_from_ns bigint,
  label text, agent text, confidence real, evidence_ref text, supersedes_ns bigint
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'clt_label',
  kudu_table 'impala::signals_dataproducts.clt_label', access 'kudu_scan');

CREATE FOREIGN TABLE clt_activation_tier0 (
  epoch_hour integer, ts_ns bigint, text_id bigint, pos integer, layer smallint,
  feat_idx integer[], feat_val real[], nnz integer, agent text, ref text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'clt_activation_tier0',
  kudu_table 'impala::signals_dataproducts.clt_activation_tier0', access 'kudu_scan');
