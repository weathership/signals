# Kudu

Apache Kudu is the hot-tier store: low-latency upserts and analytical
scans on weekly range partitions. Iceberg on RustFS holds settled
weeks. See [Query Engine](../architecture/query-engine.md).

## Role in the Stack

Kudu stores the primary (hot) copy of analytical tables. Tables are created via Impala's `STORED AS KUDU` syntax and managed by Kudu's master server. In HMS-free mode, table metadata is registered in a PostgreSQL catalog registry rather than the Hive Metastore.

```
Impala DDL → KuduCatalogOpExecutor → Kudu Master → Tablet Servers
                                   → PG catalog registry
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| kudu-master | 7051 (RPC), 8051 (HTTP) | Schema management, tablet locations |
| kudu-tserver | 7050 (RPC), 8050 (HTTP) | Data storage, scan execution |

## Table Naming

Kudu tables created through Impala use the naming convention `impala::<db>.<table>`. This is stored as the `kudu.table_name` property in the metastore table object and in the PostgreSQL catalog registry.

## Data Lifecycle

Tables begin in Kudu (hot tier) and can be migrated to Iceberg (warm tier) via `CREATE TABLE ... AS SELECT` through Impala:

```sql
-- Hot tier: Kudu (low-latency reads/writes)
CREATE TABLE db.events (
  event_id INT, ts BIGINT, data STRING,
  PRIMARY KEY(event_id)
) STORED AS KUDU;

-- Warm tier: migrate to Iceberg via Polaris
CREATE TABLE db.events_archive
  STORED AS ICEBERG
  TBLPROPERTIES('iceberg.catalog'='polaris')
AS SELECT * FROM db.events WHERE ts < 1710000000;
```

## Build

Kudu requires both C++ binaries and a Java client:

- **C++ binaries**: Built from `components/kudu/` with cmake/ninja. The Impala toolchain includes a pre-built Kudu client for ABI compatibility.
- **Java client**: `kudu-client` via `devenv tasks run kudu:install-java` into **`.devenv/m2`** (project Maven repo), not `~/.m2`.

Build dependencies: cmake, ninja, gcc, protobuf, flatbuffers, cyrus_sasl, openssl.
