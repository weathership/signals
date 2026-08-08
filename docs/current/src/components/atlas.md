# Atlas

Apache Atlas provides metadata governance and data catalog capabilities. In Signals 360, Atlas is the central metadata catalog where all Impala tables and columns are registered, classified, and tagged with BFO-grounded governance metadata.

## Role in the Stack

Atlas serves two purposes:

1. **Metadata catalog** — Every table and column created in Impala becomes a discoverable entity in Atlas with type information, ownership, and lineage.
2. **Classification target** — An external AI/ML tagging service annotates Atlas entities with SIGDG ontology labels, enabling tag-based access control via Ranger.

See [Metadata Tagging](../architecture/meta-tagging.md) for the classification architecture and SIGDG ontology.

## Services

| Service | Port | Purpose |
|---------|------|---------|
| Atlas | 21010 | Web UI and REST API (admin/admin); :21010 avoids clash with aegir Atlas on :21000 |

Atlas uses PostgreSQL with the Apache AGE graph extension as its backend (replacing the default JanusGraph/HBase/Solr stack).

## AGE Backend

The Atlas fork (`rch/asf-atlas`, **`rch/devenv`** line; AGE work may land here or as host config) includes a graph database backend that uses Apache AGE (A Graph Extension for PostgreSQL):

- **Module**: `components/atlas/graphdb/age/` — 26 Java files implementing all `graphdb/api` interfaces
- **Backend class**: `AtlasAgeGraphDatabase` loaded via `atlas.graphdb.backend` config property
- **Graph queries**: openCypher via AGE, stored in PostgreSQL

This eliminates the HBase + Solr dependencies from the standard Atlas deployment.

## Impala / Kudu Integration

Impala-managed **Kudu** tables are registered in Atlas with the stock **RDBMS** model
(`addons/models/2000-RDBMS/`) — same family as Aegir (`rdbms_*`). A Python catalog
bridge reads table metadata from Impala via `DESCRIBE` and creates entities through
the Atlas REST API. Hive entity types are not used for product registration.

### Entity Types

| Atlas Entity Type | qualifiedName Pattern | Source |
|-------------------|----------------------|--------|
| `rdbms_instance` | `instance@signals` | Lab cluster (`rdbms_type=Kudu`) |
| `rdbms_db` | `{db}@signals` | CREATE DATABASE |
| `rdbms_table` | `{db}.{table}@signals` | CREATE TABLE |
| `rdbms_column` | `{db}.{table}.{col}@signals` | Column definitions from Kudu schema |

Relationships: `rdbms_instance_databases` → `rdbms_db_tables` → `rdbms_table_columns`
(COMPOSITION). Atlas resolves these when entities are created via `POST /v2/entity/bulk`
with temporary GUIDs. See [Roadmap: Entity Type Evolution](../reference/roadmap.md#entity-type-evolution).

### Catalog Bridge

The bridge function (`register_impala_table_in_atlas` in `features/platform/steps/helpers.py`,
mirrored by `sigint.atlas_client.AtlasClient.register_table`) performs entity registration
without Kafka or the Atlas hook infrastructure:

1. `DESCRIBE {table}` on Impala → column names, types, comments
2. Build `rdbms_instance` + `rdbms_db` (referred), `rdbms_table` (main), `rdbms_column`
   (referred) entities with negative temp GUIDs (`data_type` on columns, `type=TABLE` on tables)
3. `POST /v2/entity/bulk` — single atomic call, idempotent via qualifiedName matching
4. Extract real GUIDs from `guidAssignments` (create) or `mutatedEntities` (update)

Used by the tier-1 BDD integration tests. See [Test Infrastructure](../scenarios/testing.md).

### Metadata Tagging Pipeline

```
Impala CREATE TABLE (Kudu)
    → Catalog Bridge (DESCRIBE → Atlas REST API)
        → Atlas (rdbms_table + rdbms_column entities)
            → Tagging Service (classifies against SIGDG ontology)
                → Atlas (SIGDG classifications applied)
                    → Ranger (tag-based policies enforced)
```

The tagging service reads new entities from Atlas and classifies table and column names against the SIGDG ontology (BFO-grounded data governance vocabulary). Classifications are written back as Atlas tags.

### Classification Examples

| Column Name | SIGDG Class | Sensitivity |
|-------------|-------------|-------------|
| `customer_id` | `SIGDG:0012` PlatformIdentifier | Internal |
| `email` | `SIGDG:0025` ContactInformation | Confidential |
| `ssn` | `SIGDG:0011` GovernmentIdentifier | Restricted |
| `total_amount` | `SIGDG:0021` FinancialInformation | Confidential |
| `order_status` | `SIGDG:0050` TransactionInformation | Internal |

### BDD Validation

The tier-1 integration tests validate the full classification lifecycle:

1. **Catalog bridge** — Impala table registered in Atlas with correct column metadata
2. **Classification CRUD** — Create PII classification type, apply to tables and columns
3. **Column-level tagging** — Apply classification to individual columns (e.g., `email` → PII)
4. **Entity lifecycle** — Create, register, verify, delete entities through Impala DDL + Atlas API

## Build

```bash
cd components/atlas
mkdir -p webapp/target/api/v2/apidocs/ui
mvn package -pl webapp -am -Dmaven.test.skip=true -DskipUTs=true \
  -DGRAPH-PROVIDER=age -Dcheckstyle.skip=true -DskipEnunciate=true \
  --no-transfer-progress
```

Runtime requires JDK 21 with `--add-opens` flags for HBase shaded JAXB classes.
