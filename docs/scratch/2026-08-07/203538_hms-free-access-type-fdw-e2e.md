# HMS-free Kudu access type + fdw_smoke e2e

## Goal

`SELECT * FROM fdw_smoke` (Postgres FDW → Impala HS2 → Kudu) returns rows end-to-end under HMS-free mode.

## Root causes fixed

### 1. Access type NONE (analysis)

Hive-3+ `Analyzer.ensureTableSupported()` requires a non-`NONE` table access type. HMS-free synthetic `Table` thrift objects defaulted to 0 → reported as `NONE`, so SELECT/INSERT failed with:

```
AnalysisException: Operations not supported. Table default.fdw_smoke access type is: NONE
```

**Fix:** set `ACCESSTYPE_READWRITE` (8) when constructing HMS-free metadata:

| Path | File |
|------|------|
| Catalogd table load | `TableLoader.loadHmsFree()` → `MetastoreShim.setTableAccessType` |
| CREATE TABLE | `SignalsDdlExecutor.createTable()` (already set earlier) |
| Local catalog provider | `KuduMetaProvider.loadTable()` |

### 2. Catalog empty after catalogd restart

`CatalogServiceCatalog.reset()` HMS-free path only seeded `default` and never reloaded `catalog_tables`, so `SHOW TABLES` was empty after restart even when PG registry + Kudu still had the table.

**Fix:** `loadHmsFreeCatalogFromRegistry()` loads DBs + Kudu table names from PostgreSQL `signals_catalog` as `IncompleteTable` placeholders (schema still loaded from Kudu on demand).

### 3. DML cancelled by HS2 client

UPSERT analyzed fine (access type OK) but finished with `Query Status: Cancelled` because `impala_hs2_execute` returned as soon as `ExecuteStatement` replied and `CloseOperation` ran while fragments were still starting.

**Fix:** `components/impala_fdw/src/exec_impala.cpp` — `runAsync=true` + poll `GetOperationStatus` until `FINISHED_STATE` before returning/closing.

Also: `registerTable` uses `ON CONFLICT … DO UPDATE` so re-register after partial failures is idempotent.

## Verified

```text
# HS2
UPSERT INTO fdw_smoke VALUES (1,'alpha'),(2,'beta'),(3,'gamma')  → FINISHED
SELECT * FROM fdw_smoke ORDER BY id  → 3 rows
SELECT count(*) FROM fdw_smoke       → 3

# Postgres :5455/signals
SELECT * FROM fdw_smoke ORDER BY id;
 id | name
----+-------
  1 | alpha
  2 | beta
  3 | gamma
```

Stack: `devenv up -d` (single process manager; avoid dual daemons). FE: `devenv tasks run impala:build-fe`. FDW: `impala-fdw:build` + `impala-fdw:install`.

## Ops notes

- Dual `daemon-processes` instances fight over Impala ports and produce zombie impalads / unhealthy executor groups. Prefer one `devenv up -d`.
- Orphan Postgres on :5455 can leave process-compose `postgres` in `gave_up` while the port still works — fine for this smoke.
- Catalogd must restart after FE jar rebuild to pick up `TableLoader` / registry-load changes.

## Files touched

- `components/impala/fe/.../TableLoader.java` (access type on HMS-free load)
- `components/impala/fe/.../SignalsDdlExecutor.java` (access type on create)
- `components/impala/fe/.../CatalogServiceCatalog.java` (registry reload on reset)
- `components/impala/fe/.../KuduMetaProvider.java` (access type + upsert register)
- `components/impala_fdw/src/exec_impala.cpp` (wait for op completion)
