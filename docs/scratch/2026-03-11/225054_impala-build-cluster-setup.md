# Impala Build + Running Cluster Setup

## What Was Done

### Step 1: Build Configuration (complete)

**Files created/modified in `components/impala/`:**

- `bin/impala-config-branch.sh` — Set `USE_APACHE_COMPONENTS=true`, `USE_APACHE_HIVE_3=true`, `IMPALA_KUDU_VERSION=1.19.0-SNAPSHOT`
- `bin/impala-config-local.sh` — Created: `USE_SYSTEM_GCC=1`, `SKIP_PYTHON_DOWNLOAD=true`, `DOWNLOAD_CDH_COMPONENTS=false`
- `java/pom.xml` — Enabled snapshots on `impala.toolchain.kudu.repo` (line ~125: `<enabled>true</enabled>`)

### Step 2: Kudu Java Client (COMPLETE)

Published `org.apache.kudu:kudu-client:1.19.0-SNAPSHOT` to `~/.m2/repository/`.

**Problem:** Kudu's Gradle wrapper is 7.6.4, incompatible with JDK 21 (class version 65).

**Fixes applied in `~/local/src/asf/kudu/java/` (5 files):**
1. `gradle/wrapper/gradle-wrapper.properties` — Changed to `gradle-8.5-all.zip`
2. `buildSrc/.../DistTestTask.java:278-279` — `getFiles()` → `new ArrayList<>(getFiles())` (Set→List)
3. `gradle/quality.gradle:127-131` — `csv.enabled false` → `csv.required = false` (Gradle 8.x)
4. `gradle/shadow.gradle:22,34,36` — Plugin `com.github.johnrengelman.shadow` → `com.gradleup.shadow`; `classifier` → `archiveClassifier`
5. `gradle/benchmarks.gradle:20,30` — Plugin `me.champeau.gradle.jmh` → `me.champeau.jmh`; `duplicateClassesStrategy` takes `DuplicatesStrategy.EXCLUDE` enum
6. `buildSrc/build.gradle:30,41` — Shadow plugin `7.1.2` → `com.gradleup.shadow:8.3.6`; JMH plugin `0.5.3` → `me.champeau.jmh:0.7.2`

### Step 3: Kudu C++ Build (blocked on OpenSSL)

**Problem:** Kudu's thirdparty `libcurl.a` was compiled against OpenSSL 3.2+ headers, references `SSL_get0_group_name`. The devenv shell provides OpenSSL 3.0.19 which lacks this symbol.

**Fix:** Changed `devenv.nix` from `openssl_3` to `openssl` (3.6.1). **Requires devenv shell reload** for cmake to find the new OpenSSL.

Build commands after reload:
```bash
cd ~/local/src/asf/kudu/build/release
rm -f CMakeCache.txt  # clear old OpenSSL paths
cmake -DCMAKE_BUILD_TYPE=Release -GNinja -DNO_TESTS=1 ../..
ninja kudu-master kudu-tserver
ln -sfn $(pwd) ../latest
```

### Steps 6-7: devenv.nix Updates (complete)

Added to `devenv.nix`:

**Processes:**
- `impala-statestore` — port 24000, web UI 25010
- `impala-catalogd` — port 26000, web UI 25020 (HMS at thrift://localhost:9083)
- `impala-impalad` — HS2 port 21050, beeswax port 21001 (avoids Atlas 21000 conflict), web UI 25000

**Tasks:**
- `kudu:install-java` — Gradle publishToMavenLocal
- `kudu:build-cpp` — cmake + ninja (with OpenSSL cache detection)
- `impala:bootstrap` — Download Impala toolchain (~5-10 GB)
- `impala:build` — Full buildall.sh
- `impala:build-fe` — Java-only incremental build
- `impala:test-fe` — Run signals-specific FE tests

### Step 8: Unit Tests (complete)

**Files created/modified in `components/impala/fe/src/test/java/`:**

1. `org/apache/impala/service/catalogmanager/ConfigLoaderTest.java` — Added 3 tests:
   - `testKuduConnectorValid()` — Validates `connector.name=kudu` is accepted
   - `testUnsupportedConnectorThrows()` — Validates unknown connector rejected
   - `testMixedConnectors()` — Mixed iceberg + kudu configs in same directory

2. `org/apache/impala/catalog/local/KuduMetaProviderTest.java` — New, 14 tests using in-memory Derby:
   - Database CRUD: loadDbList, loadDb, loadDbNotFound, createAndDropDatabase
   - Table list: loadTableList, loadTableListEmptyDb, unregisterTable
   - Metadata: getURI, isReady, nullPartitionKeyValue
   - Unsupported ops: loadFunctionNames, loadDataSources, loadDataSource throw
   - Note: `loadTable()` and `registerTable()` use PG-specific `::text`/`::jsonb` casts — covered by integration tests

3. `org/apache/impala/service/SignalsDdlExecutorTest.java` — New, 8 tests using Mockito:
   - createDatabase: default location, custom location, if_not_exists with duplicate, duplicate without if_not_exists
   - dropDatabase: success, if_exists on failure, failure without if_exists
   - dropTable: success, if_exists on failure, failure without if_exists

## Remaining Steps

### Steps 4-5: Impala Toolchain + Build
After devenv reload and Kudu C++ build succeeds:
```bash
cd components/impala
source bin/impala-config.sh
python3 bin/bootstrap_toolchain.py  # ~5-10 GB download
./buildall.sh -notests -noclean     # ~30-90 min
```

### Verification: Running SQL
See plan for Phase A (with HMS) and Phase B (HMS-free) SQL commands.

## Port Assignments

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 5455 | Database |
| KDC | 8848 | Kerberos |
| Kudu Master | 7051 (RPC), 8051 (web) | Storage |
| Kudu TServer | 7050 (RPC), 8050 (web) | Storage |
| HMS | 9083 | Hive Metastore |
| Polaris | 8181 | Iceberg REST Catalog |
| Atlas | 21000 | Metadata Governance |
| Impala Statestore | 24000, 25010 (web) | Cluster Coordination |
| Impala Catalogd | 26000, 25020 (web) | Catalog Service |
| Impala Daemon | 21050 (HS2), 21001 (beeswax), 25000 (web), 27000 (KRPC) | Query Execution |
