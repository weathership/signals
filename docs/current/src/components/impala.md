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

Prefer host tasks so Maven/Ranger isolation stays under `.devenv/`:

```bash
devenv tasks run impala:bootstrap   # toolchain (long first time)
devenv tasks run impala:build       # or scripts/impala-build-isolated.sh
```

Produces `impalad`, `catalogd`, `statestored`, `admissiond` under
`be/build/latest/service/`.

### Hadoop is a build tax — not a signals storage tier

**Runtime product path:** Kudu (and later Iceberg via Polaris). No HDFS NameNode,
DataNode, YARN, or HBase. HMS-free catalog lives in PostgreSQL. That is the
asf-signals intent; see [Query Engine](../architecture/query-engine.md).

**Build reality (upstream Impala):** the tree is still **HDFS-first**. CMake does
`find_package(HDFS REQUIRED)` (libhdfs), packaging expects `libhadoop.so`, and the
FE still compiles against Hadoop client jars. Bootstrap therefore materializes a
Hadoop **client/native tarball** (CDP or Apache under `toolchain/`) even though
signals never runs a Hadoop cluster for Kudu-only tables.

| Layer | Still wants Hadoop | Signals need |
|-------|--------------------|--------------|
| BE link | libhdfs | Unwanted for pure Kudu; hard-linked today |
| Package check | `libhadoop.so` | Distro packaging leftover |
| FE Maven | hadoop-hdfs / client APIs | Only if HDFS table types compile in |
| Runtime services | HDFS/YARN | **None** for Kudu-only |

Treat the tarball as a **link-time SDK**, not a product component. Do not document
“running Hadoop” as part of devenv services.

**Direction (when appropriate, on `rch/devenv`):** optional Kudu-only / no-HDFS
build profile that stubs or drops HDFS BE I/O and fails closed if anything opens
`hdfs://`. Same class of interim debt as Ranger JDK 11/Nashorn — not the end state.