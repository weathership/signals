-- Atlas typed Kudu projections (HMS-free Impala DDL)
-- Freeze: docs/scratch/2026-08-07/211412_atlas-kudu-projection-freeze.md
-- Apply: just atlas-kudu-projections-seed
--
-- AGE = SoR. These tables are derived projections (UPSERT sync).
-- Lab PARTITION counts; prod: HASH ≈ 2–3× tservers; audit may add RANGE months.

CREATE DATABASE IF NOT EXISTS atlas;

-- ── entity_flat ─────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS atlas.entity_flat;
CREATE TABLE atlas.entity_flat (
  guid BINARY NOT NULL,
  type_name STRING NOT NULL,
  qualified_name STRING,
  name STRING,
  state TINYINT,
  created_ts BIGINT,
  updated_ts BIGINT,
  props_json STRING,
  PRIMARY KEY (guid)
)
PARTITION BY HASH (guid) PARTITIONS 4
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'entity_flat',
  'signals.props_json' = 'cold_only'
);

-- ── entity_by_qn (secondary index; digest = first_16(SHA256(type ‖ 0x1f ‖ qn)))
DROP TABLE IF EXISTS atlas.entity_by_qn;
CREATE TABLE atlas.entity_by_qn (
  qn_digest BINARY NOT NULL,
  guid BINARY NOT NULL,
  type_name STRING NOT NULL,
  PRIMARY KEY (qn_digest)
)
PARTITION BY HASH (qn_digest) PARTITIONS 4
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'entity_by_qn',
  'signals.digest' = 'sha256_16(type_name || 0x1f || qualified_name)'
);

-- ── edge_out / edge_in ──────────────────────────────────────────────────────
-- NOTE: Impala→Kudu cannot apply predicates on BINARY columns
-- ("Unsupported Kudu type considered for predicate: BINARY"). Store identity
-- as fixed 32-char hex STRING for HS2 pushdown; libkudu_client path may use
-- BINARY later without changing the logical key.
DROP TABLE IF EXISTS atlas.edge_out;
CREATE TABLE atlas.edge_out (
  src STRING NOT NULL,
  elabel STRING NOT NULL,
  dst STRING NOT NULL,
  dst_type STRING,
  PRIMARY KEY (src, elabel, dst)
)
PARTITION BY HASH (src) PARTITIONS 4
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'edge_out',
  'signals.guid_encoding' = 'hex32'
);

DROP TABLE IF EXISTS atlas.edge_in;
CREATE TABLE atlas.edge_in (
  dst STRING NOT NULL,
  elabel STRING NOT NULL,
  src STRING NOT NULL,
  src_type STRING,
  PRIMARY KEY (dst, elabel, src)
)
PARTITION BY HASH (dst) PARTITIONS 4
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'edge_in',
  'signals.guid_encoding' = 'hex32'
);

-- ── entity_classifications (tag-leading PK, HASH guid; no guid-leading mirror)
DROP TABLE IF EXISTS atlas.entity_classifications;
CREATE TABLE atlas.entity_classifications (
  tag_name STRING NOT NULL,
  guid BINARY NOT NULL,
  propagate BOOLEAN,
  applied_time BIGINT,
  PRIMARY KEY (tag_name, guid)
)
PARTITION BY HASH (guid) PARTITIONS 4
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'entity_classifications',
  'signals.mirror_guid_leading' = 'false'
);

-- ── entity_audit (lab: HASH only; prod: HASH × monthly RANGE on event_ts)
DROP TABLE IF EXISTS atlas.entity_audit;
CREATE TABLE atlas.entity_audit (
  guid BINARY NOT NULL,
  event_ts BIGINT NOT NULL,
  seq BIGINT NOT NULL,
  event_type STRING,
  actor STRING,
  payload_json STRING,
  PRIMARY KEY (guid, event_ts, seq)
)
PARTITION BY HASH (guid) PARTITIONS 2
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'entity_audit',
  'signals.range_plan' = 'monthly_event_ts_prod'
);
