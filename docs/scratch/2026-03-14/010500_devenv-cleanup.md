# devenv.nix Cleanup: Clean `devenv up`

## Summary

Cleaned up devenv.nix so `devenv up` starts only the core stack (PG, KDC, Kudu, Impala) with proper dependency ordering, readiness probes, and HMS-free mode active by default.

## Changes

### devenv.nix
1. **Added `let` block** with `impalaLdLibraryPath` and `hmsFreeJavaOpts` to eliminate duplication across 3 Impala processes
2. **Removed processes**: `atlas`, `hms`, `polaris` (their build/install tasks remain for on-demand use)
3. **Removed `hive_metastore` database** from `initialDatabases`
4. **Added readiness probes**: KDC (TCP 8848), kudu-master (HTTP 8051), kudu-tserver (HTTP 8050), statestore (HTTP 25010), catalogd (HTTP 25020), impalad (HTTP 25000)
5. **Added dependency chain** via `process-compose.depends_on`:
   - `kudu-tserver` waits for `kudu-master` (healthy)
   - `catalog-init` waits for `postgres` (healthy)
   - `impala-catalogd` waits for `impala-statestore` (healthy) + `kudu-tserver` (healthy) + `catalog-init` (completed)
   - `impala-impalad` waits for `impala-catalogd` (healthy)
6. **Added `catalog-init` one-shot process**: runs `psql` schema init after PG is healthy, then exits (`restart: no`)
7. **HMS-free mode**: `JAVA_TOOL_OPTIONS` set with `-Dsignals.hms_free_mode=true` on catalogd and impalad; removed `--hive_metastore_uris` flag from catalogd
8. **Removed all `sleep` hacks**: replaced by `depends_on` with `process_healthy` conditions
9. **Added binary existence checks** to all 3 Impala processes
10. **Updated `enterShell`**: shows core services, JDBC connect string, build tasks first then utility tasks

### config/impala/hive-site.xml
- Removed `hive.metastore.uris` property (no longer connecting to HMS)

## Process Count
- Before: 10 processes (PG, KDC, Atlas, HMS, Polaris, kudu-master, kudu-tserver, statestore, catalogd, impalad)
- After: 9 processes (PG, KDC, Atlas, kudu-master, kudu-tserver, catalog-init, statestore, catalogd, impalad)

## Dependency Graph
```
PostgreSQL (built-in readiness)
  |
  +-- catalog-init (one-shot, restart=no)
  |
  +-- KDC (independent, TCP readiness on 8848)
  |
  +-- kudu-master (HTTP readiness on 8051)
        |
        +-- kudu-tserver (HTTP readiness on 8050)
              |
              +-- impala-statestore (HTTP readiness on 25010)
                    |
                    +-- impala-catalogd (HTTP readiness on 25020)
                          |   depends on: statestore@healthy + tserver@healthy + catalog-init@completed
                          |
                          +-- impala-impalad (HTTP readiness on 25000)
```
