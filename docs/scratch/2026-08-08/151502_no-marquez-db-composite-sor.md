# No Marquez DB — composite SoR in Atlas/signals

**Date:** 2026-08-08

## Decision

Do **not** create a separate `marquez` PostgreSQL database or run stock Marquez
API as a second catalog. OpenLineage lives in the **Atlas/signals** store
(AGE + additive OL types). Scale via **FDW / kudu_scan** projections, not by
cloning Marquez Flyway tables.

## Devenv

- `processes.marquez-web` — **default stack** (always with `devenv up` / `-d`); UI only (`:3000`), depends on Atlas; proxies `/api/v1` → Atlas
- `languages.javascript` + `tasks.marquez:build-web` (`before = devenv:processes:marquez-web`) — turn-key first run
- Removed: `marquez:db-init`, `marquez` initialDatabase, stock `marquez-api` process

## Flink

Dual-path validation: upstream Flink OL → Atlas OL ingest; Atlas clients
unchanged. Feature skeleton: `features/platform/lineage_flink_ol.feature` (@wip).
