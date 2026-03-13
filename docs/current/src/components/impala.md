# Impala

Apache Impala provides a distributed SQL query engine for interactive analysis. In Signals 360, Impala is the SQL interface for all analytical queries across Kudu (hot tier) and Iceberg (warm tier) tables.

## Role in the Stack

Impala runs in HMS-free mode, eliminating the dependency on the Hive Metastore. DDL operations route through `SignalsDdlExecutor` to create tables directly in Kudu or via the Polaris REST catalog for Iceberg. Table metadata is loaded from Kudu master (not HMS) at query time.

See [Query Engine & Catalog Stack](../architecture/query-engine.md) for the full architecture.

## Services

| Service | Port | Purpose |
|---------|------|---------|
| statestore | 24000 | Cluster membership, metadata broadcast |
| catalogd | 26000 | Metadata management, DDL execution |
| impalad | 21050 (HS2), 21001 (beeswax) | Query execution, client connections |

Web UIs: statestore `:25010`, catalogd `:25020`, impalad `:25000`.

## Connecting

```bash
# JDBC (recommended — works with Python 3.12)
jdbc:hive2://localhost:21050/default;auth=noSasl

# impala-shell is broken with Python 3.12 (PY_SSIZE_T_CLEAN)
```

## HMS-Free DDL

```sql
-- Databases
CREATE DATABASE sample_db;
DROP DATABASE sample_db;

-- Kudu tables
CREATE TABLE sample_db.events (
  id INT, name STRING, ts BIGINT,
  PRIMARY KEY(id)
) STORED AS KUDU
TBLPROPERTIES('kudu.master_addresses'='127.0.0.1:7051');

-- Iceberg tables (via Polaris — near-term)
CREATE TABLE sample_db.archive (
  id INT, name STRING
) STORED AS ICEBERG
TBLPROPERTIES('iceberg.catalog'='polaris');
```

## Verified Operations

The following have been tested end-to-end in HMS-free mode:

- CREATE/DROP DATABASE and TABLE
- INSERT INTO (single and multi-row)
- SELECT with WHERE, ORDER BY
- Multi-table JOINs (3-way)
- GROUP BY with COUNT, SUM, CAST
- Subqueries with HAVING
- Data types: INT, STRING, DOUBLE, BOOLEAN, BIGINT

## Build

Impala is built from source using its toolchain (GCC 10.4.0, Thrift, LLVM, etc.):

```bash
cd components/impala
source bin/impala-config.sh
./buildall.sh -notests -noclean
```

The build produces four binaries: `impalad`, `catalogd`, `statestored`, `admissiond` in `be/build/latest/service/`.

Build dependencies: cmake, ninja, gcc, protobuf, flatbuffers. The Impala toolchain downloads additional dependencies (~5-10 GB) via `bootstrap_toolchain.py`.
