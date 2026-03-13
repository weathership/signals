# Query Engine + Catalog Stack Implementation (HMS Elimination)

## Summary

Implemented the three-phase plan for eliminating HMS from the Impala query path,
replacing it with a PostgreSQL-backed catalog registry for Kudu tables and Polaris
REST catalog for Iceberg tables.

## Decision: Impala over Trino

Trino was evaluated but rejected because **Trino 473+ removed the Kudu connector**
(Kudu is incompatible with Java 24 which Trino now requires). Only Starburst
(commercial) retains Kudu support. If Kudu is phased out in the future, Trino
becomes the natural migration target (zero HMS dependency, native Polaris support).

## Changes Made

### Phase 1: Standalone HMS + Infrastructure

**devenv.nix** — Added processes and tasks:
- `processes.hms` — Hive Standalone Metastore backed by PostgreSQL
- `processes.polaris` — Apache Polaris (Iceberg REST catalog)
- `processes.kudu-master` — Kudu master at localhost:7051
- `processes.kudu-tserver` — Kudu tablet server at localhost:7050
- `tasks.hms:install` — Download HMS 4.0.1 binary + PostgreSQL JDBC driver
- `tasks.hms:init-schema` — Initialize HMS schema via MetastoreSchemaTool
- `tasks.polaris:install` — Build Polaris from source
- `tasks.signals:catalog-init` — Initialize catalog registry schema
- Added `hive_metastore`, `polaris`, `signals_catalog` databases to PostgreSQL init

**Config files created:**
- `config/hms/metastore-site.xml` — HMS config for PostgreSQL, auto-schema, local warehouse
- `config/polaris/application.properties` — Polaris JDBC + HTTP config
- `config/impala/catalog_config_dir/polaris.properties` — Iceberg REST catalog connector
- `config/impala/catalog_config_dir/kudu.properties` — Kudu connector config
- `config/impala/catalog_schema.sql` — PostgreSQL catalog registry DDL

### Phase 2: IcebergRESTCatalog DDL

**IcebergRESTCatalog.java** — Implemented three DDL methods:
- `createTable()` — delegates to `restCatalog_.buildTable().create()`
- `dropTable(FeIcebergTable)` — delegates to `restCatalog_.dropTable()`
- `dropTable(dbName, tblName)` — delegates to `restCatalog_.dropTable()`
- `renameTable()` — delegates to `restCatalog_.renameTable()`

### Phase 3: HMS Elimination

**KuduMetaProvider.java** (new, 390 lines) — PostgreSQL-backed MetaProvider:
- Implements full `MetaProvider` interface following `IcebergMetaProvider` pattern
- `loadDbList()` / `loadDb()` — queries `catalog_databases` table
- `loadTableList()` / `loadTable()` — queries `catalog_tables` for KUDU type
- `loadTable()` constructs HMS-compatible `Table` object with Kudu properties
  (storage_handler, master_addresses, table_name) so `LocalKuduTable.loadFromKudu()`
  can derive the actual schema from Kudu master
- DDL helpers: `createDatabase()`, `dropDatabase()`, `registerTable()`, `unregisterTable()`
- Inner classes: `KuduTableMetaRefImpl`, `KuduPartitionRefImpl`, `KuduPartitionMetadataImpl`

**SignalsDdlExecutor.java** (new, 155 lines) — HMS-free DDL routing:
- `createDatabase()` / `dropDatabase()` — catalog registry only
- `createTable()` — routes to `KuduCatalogOpExecutor.createSynchronizedTable()` + registry
- `dropTable()` — unregisters from catalog registry

**ConfigLoader.java** — Extended connector support:
- New `checkConnectorName()` method accepts both `iceberg` and `kudu` connector types
- `kudu` connector doesn't require `iceberg.catalog.type`

**LocalImpl.java** — Added KuduMetaProvider support:
- `getSecondaryProviders()` now checks `connector.name` to instantiate either
  `IcebergMetaProvider` or `KuduMetaProvider` (wrapped in `BlacklistingMetaProvider`)

**CatalogOpExecutor.java** — HMS-free mode guard:
- New `HMS_FREE_MODE` static flag (`-Dsignals.hms_free_mode=true`)
- New `signalsDdlExecutor_` field initialized from system properties
- Guard in `execDdlRequest()` intercepts CREATE_DATABASE, DROP_DATABASE,
  CREATE_TABLE, CREATE_TABLE_AS_SELECT, DROP_TABLE — routes to SignalsDdlExecutor
- Other DDL types fall through to standard HMS-based paths

## Architecture

```
Phase 1 (bootstrap):
  PostgreSQL ← HMS → Impala → Kudu Master
                        ↓
                     Polaris (Iceberg REST)

Phase 3 (HMS eliminated):
  PostgreSQL (catalog_databases, catalog_tables)
       ↓
  KuduMetaProvider → LocalKuduTable → Kudu Master
  IcebergMetaProvider → IcebergRESTCatalog → Polaris → Iceberg tables
       ↓
  MultiMetaProvider (chains both)
       ↓
  LocalCatalog → Impala query engine
```

## Activation

Phase 1-2 (with HMS): standard Impala startup
Phase 3 (HMS-free): add JVM flags:
```
-Dsignals.hms_free_mode=true
-Dsignals.catalog.jdbc_url=jdbc:postgresql://localhost:5455/signals_catalog
-Dsignals.kudu.master_addresses=127.0.0.1:7051
```

## Future: gRPC over Thrift

The current implementation uses Thrift types (e.g., `hive_metastore.api.Table`,
`TDdlExecRequest`) because Impala's internal APIs are Thrift-based. A future
refactor could replace Thrift with gRPC for the catalog service interface,
which would align with the broader gRPC architecture used by the signals engine.
This would require defining protobuf messages for the catalog API and modifying
the frontend-to-catalogd communication layer.

## Key Insight

HMS is essentially a "table of contents" — `(database, table_name) → (type, properties)`.
For Kudu, the actual schema always comes from Kudu master (`LocalKuduTable` line 79:
"Use the schema derived from Kudu, rather than the one stored in the HMS").
For Iceberg, metadata lives in Polaris. The PostgreSQL catalog registry replaces
HMS's role as this lookup table.
