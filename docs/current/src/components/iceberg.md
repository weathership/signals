# Iceberg

Apache Iceberg provides an open table format for large analytic datasets with schema evolution, hidden partitioning, and time travel.

## Role in the Stack

Iceberg serves as the warm-tier storage format. Tables are managed through the Polaris REST catalog and queried via Impala. Data migrates from Kudu (hot) to Iceberg (warm) as it ages, using `CREATE TABLE ... AS SELECT` through Impala.

```
Impala DDL → IcebergCatalogOpExecutor → Polaris REST Catalog → Object Storage
```

## Polaris REST Catalog

[Apache Polaris](https://polaris.apache.org/) provides the Iceberg REST catalog API (port 8181). It manages Iceberg table metadata, namespace operations, and storage credentials. Polaris is backed by PostgreSQL for metadata persistence.

| Service | Port | Purpose |
|---------|------|---------|
| Polaris | 8181 | Iceberg REST catalog API |

### Impala Integration

The `IcebergRESTCatalog` class in the Impala fork implements `createTable`, `dropTable`, and `renameTable` against the Polaris REST API. Catalog configuration is in `config/impala/catalog_config_dir/polaris.properties`:

```properties
connector.name=iceberg
iceberg.catalog.type=rest
uri=http://localhost:8181/api/catalog
iceberg.rest.warehouse=signals
```

## Current Status

- **Implemented**: `IcebergRESTCatalog.createTable()`, `dropTable()`, `renameTable()` in the Impala fork
- **Near-term**: End-to-end testing of Iceberg table creation via Polaris, SELECT queries on Iceberg tables, Kudu-to-Iceberg data migration

## Data Lifecycle

```
Hot (Kudu)  ──CTAS──►  Warm (Iceberg/Polaris)  ──archive──►  Cold (S3/Object Storage)
 - Low-latency R/W       - Batch analytics              - Long-term retention
 - Recent data            - Historical data              - Compliance
```
