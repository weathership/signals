-- gaius.theta.cycle — THS storage family "scratch" (Kudu tier0).
--
-- Product id: gaius.theta.cycle
-- Storage:    signals_dataproducts.theta_scratch_{vertex,edge,incidence}_tier0
--             (Iceberg tier1 via Polaris, same grain — not Impala CREATE ICEBERG;
--             MultiMetaProvider cannot load Impala-written Iceberg metadata.
--             Polar register is the settle PR; views are tier0-only until then.)
--
-- Hypergraph: vertices + hyperedges + incidence. One hyperedge may touch many
-- vertices (window × feature × label × hx-trace). Data-fusion (later) reads
-- settled Iceberg; AGE is Atlas+OL only — not the contemplation graph SoR.
--
-- Time grain = UTC hour (epoch_hour). Expire hot with DROP RANGE PARTITION
-- VALUE = <epoch_hour> after Iceberg verify (never row DELETE). Catch-all
-- VALUES < 0; live hours ADD RANGE PARTITION like gpu_metrics_tier0.
-- Writers (remainder admit) must ADD the hour before INSERT.
--
-- Arrays are payload-only and omitted: every filterable dimension is a scalar
-- (Kudu cannot predicate arrays). Impala reserved: not `role` (use vertex_role),
-- not trigger/scope/position.
--
-- pglite: do not CREATE these tables there.

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

-- Vertices of the contemplation hypergraph (remainder windows, CLT/SAE
-- features, prefLabels, HX trace refs). Remainder windows: kind='window'
-- and reason in ('none','ambiguous').
CREATE TABLE IF NOT EXISTS signals_dataproducts.theta_scratch_vertex_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  vertex_id STRING,
  kind STRING,
  text_id BIGINT,
  layer INT,
  feature_idx INT,
  window_start INT,
  window_end INT,
  reason STRING,
  tau FLOAT,
  margin FLOAT,
  c_epoch STRING,
  aperture STRING,
  hx_generation_id STRING,
  PRIMARY KEY (epoch_hour, ts_ns, vertex_id)
)
PARTITION BY HASH (vertex_id) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 0
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.range_unit' = 'hour',
  'signals.range_width_hours' = '1',
  'signals.product' = 'gaius.theta.cycle',
  'signals.storage' = 'scratch',
  'signals.writer' = 'gaius axis_admit / theta (impala_fdw kudu_scan)'
);

-- Hyperedges (n-ary). kind: ACTIVATES | CONTEMPLATES | LABELED | SUBSUMES | EXTENDS_C
CREATE TABLE IF NOT EXISTS signals_dataproducts.theta_scratch_edge_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  edge_id STRING,
  kind STRING,
  arity INT,
  c_epoch STRING,
  PRIMARY KEY (epoch_hour, ts_ns, edge_id)
)
PARTITION BY HASH (edge_id) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 0
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.range_unit' = 'hour',
  'signals.range_width_hours' = '1',
  'signals.product' = 'gaius.theta.cycle',
  'signals.storage' = 'scratch'
);

-- Incidence I ⊆ E × V (hypergraph). pos orders members of one edge.
CREATE TABLE IF NOT EXISTS signals_dataproducts.theta_scratch_incidence_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  edge_id STRING,
  vertex_id STRING,
  vertex_role STRING,
  pos INT,
  PRIMARY KEY (epoch_hour, ts_ns, edge_id, vertex_id, vertex_role)
)
PARTITION BY HASH (edge_id) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 0
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.range_unit' = 'hour',
  'signals.range_width_hours' = '1',
  'signals.product' = 'gaius.theta.cycle',
  'signals.storage' = 'scratch'
);

-- Logical names. tier0-only until Polar-registered *_tier1 exists; then each
-- becomes UNION ALL masked by tier0 hours (gpu_metrics / signal).
CREATE VIEW IF NOT EXISTS signals_dataproducts.theta_scratch_vertex AS
SELECT * FROM signals_dataproducts.theta_scratch_vertex_tier0;
CREATE VIEW IF NOT EXISTS signals_dataproducts.theta_scratch_edge AS
SELECT * FROM signals_dataproducts.theta_scratch_edge_tier0;
CREATE VIEW IF NOT EXISTS signals_dataproducts.theta_scratch_incidence AS
SELECT * FROM signals_dataproducts.theta_scratch_incidence_tier0;
