# HMS-Free Kudu Table Lifecycle: Working End-to-End

**Date:** 2026-03-13 20:10 UTC

## Milestone

Full Kudu table lifecycle works through Impala **without HMS**:

```
CREATE DATABASE test_db                  -- OK (PG catalog registry)
DROP TABLE IF EXISTS test_db.test_kudu   -- OK (Kudu master + PG)
CREATE TABLE test_db.test_kudu (         -- OK (Kudu master + PG)
  id INT, name STRING, PRIMARY KEY(id)
) STORED AS KUDU
INSERT INTO test_db.test_kudu VALUES     -- OK (3 rows)
  (1, 'hello'), (2, 'world'), (3, 'signals')
SELECT * FROM test_db.test_kudu          -- OK (returns all 3 rows)
  ORDER BY id
```

Test is idempotent — runs cleanly on repeated execution.

## Architecture

```
Client (JDBC)
    |
    v
impalad (HS2 port 21050, HMS-free mode)
    |
    v
catalogd (port 26000, HMS-free mode)
    |
    +---> SignalsDdlExecutor (DDL routing)
    |       |
    |       +---> KuduCatalogOpExecutor (CREATE/DROP table in Kudu)
    |       +---> KuduMetaProvider (PG catalog registry)
    |
    +---> TableLoader.loadHmsFree() (metadata loading)
    |       |
    |       +---> Constructs minimal HMS Table object
    |       +---> KuduTable.load() with null msClient
    |       +---> Schema loaded from Kudu master
    |
    +---> Kudu master (7051) / tserver (7050)
    +---> PostgreSQL (5455, signals_catalog DB)
```

## Services Running

| Service     | Port  | Mode      |
|-------------|-------|-----------|
| statestore  | 24000 | standard  |
| catalogd    | 26000 | HMS-free  |
| impalad     | 21050 | HMS-free  |
| kudu-master | 7051  | standard  |
| kudu-tserver| 7050  | standard  |
| PostgreSQL  | 5455  | standard  |

No HMS, no HDFS, no HBase.

## Modified Java Files (7 total)

### New files:
1. `fe/.../service/SignalsDdlExecutor.java` — Routes DDL to Kudu/Iceberg without HMS
2. `fe/.../catalog/local/KuduMetaProvider.java` — PG-backed catalog registry

### Modified files:
3. `fe/.../service/CatalogOpExecutor.java` — HMS-free DDL block before main switch
4. `fe/.../catalog/TableLoader.java` — `loadHmsFree()` for table metadata loading
5. `fe/.../catalog/KuduTable.java` — Handle null msClient in `load()`
6. `fe/.../service/Frontend.java` — Skip MetaStoreClientPool when HMS-free
7. `fe/.../service/JniCatalog.java` — Pool size 0 in HMS-free mode
8. `fe/.../catalog/CatalogServiceCatalog.java` — Seed default DB without HMS

## Issues Fixed (chronological)

1. **TProtocolException: Required field 'status'** — HMS-free DDL paths missing `setStatus(okStatus)`
2. **DCHECK crash: request_result_set_ != nullptr** — Missing `addSummary()` in DDL response
3. **Tables not visible (INSERT/SELECT fail)** — No catalog cache update after DDL
4. **NPE in catalogOpTracker_.decrement()** — HMS-free block inside wrong try-catch scope
5. **Table exists in Kudu from previous run** — DROP TABLE only unregistered from PG, didn't drop from Kudu
6. **TableLoader.load() tries HMS** — Added `loadHmsFree()` to construct metadata from Kudu master

## Client Connectivity

- impala-shell: broken (PY_SSIZE_T_CLEAN with Python 3.12)
- impyla: broken (same Thrift C extension issue)
- **Hive JDBC with `auth=noSasl`**: works (used for all testing)

## JAVA_TOOL_OPTIONS

```
-Dsignals.hms_free_mode=true
-Dsignals.catalog.jdbc_url=jdbc:postgresql://localhost:5455/signals_catalog
-Dsignals.kudu.master_addresses=127.0.0.1:7051
```

Propagated via shell env → C++ init.cc → JVM. Confirmed working in both catalogd and impalad.

## Compile/Deploy Workflow

```bash
# From components/impala/
source bin/impala-config.sh && . bin/set-classpath.sh
javac -cp "$CLASSPATH" -d fe/target/classes -proc:none <files>
cd fe/target/classes && jar uf ../impala-frontend-5.0.0-SNAPSHOT.jar <classes>
# Restart catalogd + impalad
```

## Next Steps

- Iceberg table support (via Polaris REST catalog)
- INVALIDATE METADATA support in HMS-free mode
- Add Impala processes to devenv.nix (currently /tmp scripts)
- impala-shell fix (needs Thrift 0.16+ with Python 3.12 support)
