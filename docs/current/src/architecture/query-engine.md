# Query Engine & Catalog Stack

The query engine stack provides SQL access to analytical data without depending on the Hive Metastore (HMS), HDFS, or HBase. This is the core data infrastructure for Signals 360.

**Storage default (product):** **Kudu-only / no-HDFS.** Impala `STORED AS KUDU` is
the primary table path. HDFS is not a tier we operate. Warm analytics (Iceberg via
Polaris or similar) and future primary engines (**rustfs**, **Ceph**) are
object/block — still not HDFS. Upstream Impala’s *build* may still pull a Hadoop
**client** tarball (libhdfs / jars); that is transitional debt until the
`rch/devenv` default is a no-HDFS daemon build. See
[Impala](../components/impala.md#storage-default-kudu-only--no-hdfs).

**Access default (product):** **FDW-only / no-JDBC.** Consumers use PostgreSQL +
[impala_fdw](../components/impala_fdw.md) rather than treating Impala JDBC/HS2 as
the primary API. HS2 remains the transport behind the FDW; we slim dual client
stacks once that path is solid.

## Stack

```d2
direction: down

client: SQL Client {
  tooltip: "JDBC (HiveServer2 protocol)"
}

impalad: Impala Daemon {
  tooltip: "Query planning, execution\nHS2 port 21050"
}

catalogd: Catalog Server {
  tooltip: "Metadata management\nHMS-free mode"
  ddl: SignalsDdlExecutor
  loader: TableLoader
}

statestore: Statestore {
  tooltip: "Membership, metadata broadcast\nPort 24000"
}

kudu: Kudu {
  master: Master {tooltip: "Schema, tablet locations\nPort 7051"}
  tserver: Tablet Server {tooltip: "Data storage, scans\nPort 7050"}
}

pg: PostgreSQL {
  registry: Catalog Registry {tooltip: "catalog_databases\ncatalog_tables"}
}

polaris: Polaris {
  tooltip: "Iceberg REST catalog\nPort 8181"
}

client -> impalad: "JDBC"
impalad -> statestore: "subscribe"
impalad -> catalogd: "metadata RPCs"
catalogd -> statestore: "subscribe"
catalogd.ddl -> kudu.master: "CREATE/DROP"
catalogd.ddl -> pg.registry: "register/unregister"
catalogd.ddl -> polaris: "Iceberg DDL"
catalogd.loader -> kudu.master: "load schema"
```

## HMS-Free Mode

When `-Dsignals.hms_free_mode=true` is set, the catalog server bypasses HMS entirely:

| Operation | Standard Path | HMS-Free Path |
|-----------|---------------|---------------|
| CREATE TABLE (Kudu) | HMS → Kudu | KuduCatalogOpExecutor → Kudu + PG registry |
| CREATE TABLE (Iceberg) | HMS → Polaris | IcebergCatalogOpExecutor → Polaris — **PENDING** (see below) |
| DROP TABLE | HMS → storage | SignalsDdlExecutor → storage + PG registry |
| Load metadata | HMS getTable() | TableLoader.loadHmsFree() → Kudu master |
| CREATE/DROP DATABASE | HMS | KuduMetaProvider → PG registry |

**Iceberg DDL/DML through Impala is PENDING — in-fork, gradual, with
purpose.** The Phase-2 `IcebergRESTCatalog.createTable()` path exists but its
created metadata cannot yet be loaded back by the `MultiMetaProvider`
(2026-08-30 phantom-table incident, `#SL.00000027.SCHEMA2`), and upstream's
REST-catalog support marks tables `ACCESSTYPE_READ` ("read-only … not
supported *yet*", IMPALA-13586) so DML is gated at analysis. Doctrine: this
fork will implement the Transparent Hierarchical Storage write path over
Kudu and Iceberg through our own efforts. Until then the bridges are
`signals.ops.iceberg_register` (PyIceberg → Polaris) for tier1 DDL and
out-of-band settle (HDF5 + `IcebergHdf5Register`) for tier1 writes — bridges,
not the architecture.

### Modified Components

Eight Java files implement HMS-free mode in the Impala fork (`rch/asf-impala` on the **`rch/devenv`** line):

| File | Role |
|------|------|
| `SignalsDdlExecutor` | Routes DDL to Kudu or Iceberg without HMS |
| `KuduMetaProvider` | PostgreSQL-backed catalog registry (databases + tables) |
| `CatalogOpExecutor` | HMS-free DDL block before standard switch statement |
| `TableLoader` | `loadHmsFree()` constructs metadata from Kudu master |
| `KuduTable` | Handles null msClient in `load()` |
| `Frontend` | Skips MetaStoreClientPool when HMS-free |
| `JniCatalog` | Zero-size pool in HMS-free mode |
| `CatalogServiceCatalog` | Seeds default database without HMS |

### Catalog Registry Schema

The PostgreSQL `signals_catalog` database stores table registrations:

```sql
-- config/impala/catalog_schema.sql
CREATE TABLE catalog_databases (
    db_name TEXT PRIMARY KEY,
    comment TEXT,
    location TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE catalog_tables (
    db_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    kudu_table_name TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (db_name, table_name)
);
```

## Current Status

**Working (validated end-to-end):**
- CREATE/DROP DATABASE
- CREATE/DROP TABLE (Kudu, STORED AS KUDU)
- INSERT INTO (single and multi-row)
- SELECT with WHERE, ORDER BY, JOINs, GROUP BY, HAVING, subqueries
- Multiple data types: INT, STRING, DOUBLE, BOOLEAN, BIGINT

**Near-term:**
- Iceberg tables via Polaris REST catalog
- Atlas integration for metadata visibility and tagging

## Running the Stack

All services start via devenv or manual scripts:

```
Statestore  → port 24000  (pure C++, no JVM)
Catalogd    → port 26000  (JVM, HMS-free mode)
Impalad     → port 21050  (JVM, HS2 protocol)
Kudu Master → port 7051
Kudu TServer→ port 7050
PostgreSQL  → port 5455   (signals_catalog DB)
```

Connect via JDBC:
```
jdbc:hive2://localhost:21050/default;auth=noSasl
```
