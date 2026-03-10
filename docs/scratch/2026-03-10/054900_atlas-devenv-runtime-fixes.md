# Atlas AGE Backend — Runtime Fixes for devenv up

## Summary

After building Atlas with the AGE backend successfully, several runtime issues
were resolved to get Atlas fully starting and serving API requests via `devenv up`.

## Issues Resolved

### 1. Missing GraphDBMigrator bean

**Error:** `NoSuchBeanDefinitionException: No qualifying bean of type 'org.apache.atlas.repository.graphdb.GraphDBMigrator'`

**Cause:** The `MigrationProgressService` (injected into `AdminResource`) requires a `GraphDBMigrator` implementation. The Janus module provides `GraphDBGraphSONMigrator`, but the AGE module had none.

**Fix:** Created `AgeGraphDBMigrator.java` — a no-op implementation that:
- Parses types def JSON normally
- Throws `AtlasBaseException` on import (migration not supported with AGE)
- Returns null for migration status

### 2. openCypher query clause ordering

**Error:** `PSQLException: ERROR: syntax error at or near "ORDER"`

**Cause:** `AtlasAgeGraphQuery` placed `ORDER BY` and `SKIP`/`LIMIT` before `RETURN` in generated Cypher queries. In openCypher (used by AGE), the correct order is: `MATCH ... WHERE ... RETURN ... ORDER BY ... SKIP ... LIMIT`.

**Fix:** Reordered clause construction in `vertices()`, `vertexIds()`, and `edges()` methods to put `RETURN` before `ORDER BY`/pagination.

### 3. JDK 21 module system access

**Error:** `InaccessibleObjectException: Unable to make protected final java.lang.Class java.lang.ClassLoader.defineClass accessible: module java.base does not "opens java.lang" to unnamed module`

**Cause:** HBase's shaded JAXB implementation (used during Jersey WADL initialization) tries to use reflection on internal Java APIs, which is blocked in JDK 17+.

**Fix:** Added `--add-opens` JVM flags to the Atlas process in `devenv.nix`:
```
--add-opens java.base/java.lang=ALL-UNNAMED
--add-opens java.base/java.lang.reflect=ALL-UNNAMED
--add-opens java.base/java.io=ALL-UNNAMED
--add-opens java.base/java.net=ALL-UNNAMED
--add-opens java.base/java.util=ALL-UNNAMED
--add-opens java.base/java.util.concurrent=ALL-UNNAMED
--add-opens java.base/sun.nio.ch=ALL-UNNAMED
--add-opens java.base/sun.security.action=ALL-UNNAMED
--add-opens java.security.jgss/sun.security.krb5=ALL-UNNAMED
```

## Files Changed

| File | Change |
|------|--------|
| `graphdb/age/.../AgeGraphDBMigrator.java` | New — no-op GraphDBMigrator |
| `graphdb/age/.../AtlasAgeGraphQuery.java` | Fix: RETURN before ORDER BY/SKIP/LIMIT |
| `devenv.nix` | Add `--add-opens` JVM flags |

## Known Non-Critical Issues

- **ZK connection warnings:** CuratorFactory creates a ZK client (background thread) that tries to connect to `localhost:9026`. This is harmless noise — ZK is not needed for single-instance AGE mode.
- **Audit service error on startup:** `EmbeddedServer.auditServerStatus()` fails because audit types aren't bootstrapped. Non-blocking — server still becomes ACTIVE.

## Verification

```bash
curl -u admin:admin http://localhost:21000/api/atlas/admin/status
# {"Status":"ACTIVE"}

curl -u admin:admin http://localhost:21000/api/atlas/admin/version
# {"Description":"...","Version":"3.0.0-SNAPSHOT","Name":"apache-atlas"}

curl -u admin:admin http://localhost:21000/api/atlas/v2/types/typedefs/headers
# [] (empty — fresh install)
```
