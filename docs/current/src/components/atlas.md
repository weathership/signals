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
| Atlas | 21000 | Web UI and REST API (admin/admin) |

Atlas uses PostgreSQL with the Apache AGE graph extension as its backend (replacing the default JanusGraph/HBase/Solr stack).

## AGE Backend

The Atlas fork (`rch/signals` branch) includes a custom graph database backend that uses Apache AGE (A Graph Extension for PostgreSQL):

- **Module**: `components/atlas/graphdb/age/` — 26 Java files implementing all `graphdb/api` interfaces
- **Backend class**: `AtlasAgeGraphDatabase` loaded via `atlas.graphdb.backend` config property
- **Graph queries**: openCypher via AGE, stored in PostgreSQL

This eliminates the HBase + Solr dependencies from the standard Atlas deployment.

## Impala Integration

When Impala tables are created via HMS-free DDL, they need to be registered in Atlas as entities:

| Atlas Entity Type | Source |
|-------------------|--------|
| `impala_db` | CREATE DATABASE |
| `impala_table` | CREATE TABLE |
| `impala_column` | Column definitions from Kudu schema |

### Metadata Tagging Pipeline

```
Impala (CREATE TABLE)
    → Atlas (entity registered)
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

## Build

```bash
cd components/atlas
mkdir -p webapp/target/api/v2/apidocs/ui
mvn package -pl webapp -am -Dmaven.test.skip=true -DskipUTs=true \
  -DGRAPH-PROVIDER=age -Dcheckstyle.skip=true -DskipEnunciate=true \
  --no-transfer-progress
```

Runtime requires JDK 21 with `--add-opens` flags for HBase shaded JAXB classes.
