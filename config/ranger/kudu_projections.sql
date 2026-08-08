-- Ranger / governance Kudu projections (HMS-free Impala DDL)
-- Admin SoR remains Postgres DB "ranger". These tables are derived denorms
-- so federated engines and Impala plugins do not thrash PG under multi-engine load.
-- Apply: just ranger-kudu-projections-seed
-- Doctrine: docs/current/src/architecture/governance-scale-plane.md

CREATE DATABASE IF NOT EXISTS ranger;

-- ── tag_resource (tag-leading; bulk "who has tag T") ───────────────────────
DROP TABLE IF EXISTS ranger.tag_resource;
CREATE TABLE ranger.tag_resource (
  tag_name STRING NOT NULL,
  resource_id STRING NOT NULL,
  resource_type STRING NOT NULL,
  service_name STRING,
  owner_guid STRING,
  updated_ts BIGINT,
  PRIMARY KEY (tag_name, resource_id, resource_type)
)
PARTITION BY HASH (tag_name) PARTITIONS 4
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'ranger_tag_resource',
  'signals.sor' = 'postgres.ranger + atlas classifications'
);

-- ── resource_tag (resource-leading; bulk tags for one entity) ──────────────
DROP TABLE IF EXISTS ranger.resource_tag;
CREATE TABLE ranger.resource_tag (
  resource_id STRING NOT NULL,
  resource_type STRING NOT NULL,
  tag_name STRING NOT NULL,
  service_name STRING,
  updated_ts BIGINT,
  PRIMARY KEY (resource_id, resource_type, tag_name)
)
PARTITION BY HASH (resource_id) PARTITIONS 4
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'ranger_resource_tag'
);

-- ── policy_resource_index (eval-friendly denorm; not full policy admin) ────
DROP TABLE IF EXISTS ranger.policy_resource_index;
CREATE TABLE ranger.policy_resource_index (
  policy_id BIGINT NOT NULL,
  service_name STRING NOT NULL,
  resource_signature STRING NOT NULL,
  access_type STRING,
  is_allowed BOOLEAN,
  updated_ts BIGINT,
  PRIMARY KEY (policy_id, resource_signature)
)
PARTITION BY HASH (policy_id) PARTITIONS 2
STORED AS KUDU
TBLPROPERTIES (
  'kudu.num_tablet_replicas' = '1',
  'signals.projection' = 'ranger_policy_resource_index',
  'signals.note' = 'filled by TagSync/outbox; admin UI remains on Postgres'
);
