# No Python OL API facade

**Date:** 2026-08-08

## Decision

Do **not** ship a Python/FastAPI OpenLineage or Marquez-compat service beside
Atlas. Deleted uncommitted `src/signals/lineage/` (graph/ingest/marquez/app).

## Why

1. Target is **one process, one port**: Atlas `:21010` serves `/api/atlas/*`
   (unchanged) and `/api/v1/*` (OL ingest + Marquez-compat read).
2. A side process is immediately vestigial when that lands — dual deploy, dual
   contract surface, false “product” topology.
3. Path prefixes do not conflict; marquez-web only proxies `/api/v1`.
4. Aegir/Gaius Python code is **shape reference** for AGE labels and REST
   subset, not something to re-host in Signals.

## Next (real work)

Implement M2 in `components/atlas` webapp: Jersey (or equivalent) resources for
OpenLineage `POST /api/v1/lineage` and Marquez-compat GETs, materializing
Job/Run/Dataset into the composite signals PG/AGE store.
