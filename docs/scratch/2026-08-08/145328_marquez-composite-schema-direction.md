# Marquez + composite Atlas/OpenLineage schema (direction)

**Date:** 2026-08-08  
**Submodule:** `components/marquez` → `git@github.com:zndx/oss-marquez.git` (`main`)

## Intent

Signals is the **core product** that unifies:

| Surface | Role | Existing foundation |
|---------|------|---------------------|
| **Atlas** | Governance authority (types, classifications, rdbms_*, policies) | AGE backend, rdbms_* cutover, Kudu projections, FDW |
| **OpenLineage** | Runtime provenance (Job/Run/Dataset events + columnLineage) | Aegir polyglot OL emitters, Gaius `hx.lineage`, Aegir `gateway/marquez.py` |
| **Marquez** | OL **reference UI + REST validation suite** | oss-marquez fork; Aegir already mounts Marquez-compat read API |

Marquez is **not** the system of record and has **no separate database** in
Signals. The composite store is Atlas/signals PG (+ AGE, + Kudu/FDW for scale).
Marquez-web is an optional OL-consuming UI against the Atlas OL extension.
Stock Marquez API/Flyway schema is intentionally not deployed.

## Prior art (directional)

### Aegir
- `src/aegir/gateway/marquez.py` — Marquez-compatible `/api/v1` read surface over
  AGE graph (namespaces, jobs, runs, datasets, lineage). Explicit doctrine:
  *“Atlas remains the governance authority; this is the OL-ecosystem read surface.”*
- Polyglot: `openlineage_run_event` / columnLineage from SQL → OL JSON.
- Strategy notes (`sdg-strat-design_*`): one declaration yields OL events (Marquez-compat),
  cache keys, and impact analysis — “Atlas/OpenLineage are one graph viewed from three angles.”

### Gaius
- `gaius.hx.lineage` — OpenLineage types + emitter → PG events + AGE graph.
- Meta schema / Metabase: catalogs derived from OL events.
- Lineage graph labels align with Marquez mental model: Dataset, Job, Run + edges.

## Composite schema (target shape)

A **single PostgreSQL database** (or tightly federated schemas) that subsumes:

1. **Atlas AGE graph** — entity identity, classifications, relationships (already on `signals` PG).
2. **OL event log** — append-only RunEvents (JSON or normalized tables) Marquez expects.
3. **OL projection tables** — Marquez Postgres backend tables *or* a view layer that
   materializes the same shape from (1)+(2).

Recommended phasing:

| Phase | Deliverable |
|-------|-------------|
| M0 | Submodule + notes (this) |
| M1 | Stand up Marquez API against stock OL schema on lab PG (validation harness) |
| M2 | Map Aegir-style Marquez REST onto signals AGE + OL event store (compat layer) |
| M3 | Composite physical schema: Atlas vertices/edges + OL runs/jobs/datasets co-located |
| M4 | Writers: Impala/Airflow/polyglot/sigint emit OL; Atlas tags stay first-class |
| M5 | Marquez-web points at signals gateway; dual UI optional |

## Why this is reasonable

1. **Separation of concerns:** Atlas = governance semantics; OL = operational lineage;
   Marquez = compliance with the OL ecosystem UI/API contract.
2. **Validation without capture:** Owning Marquez (fork) lets us extend schema while
   continuously checking reference UI still works — same pattern as owning Atlas/Kudu forks.
3. **Builds on working prototypes:** Aegir already proved “AGE graph → Marquez REST”;
   Gaius proved “emit OL → AGE”; signals already has Atlas AGE + rdbms_* + stack ops.
4. **Avoids dual truth:** Composite schema + single write path; Marquez is a lens, not a second catalog.

## Risks / non-goals

| Risk | Mitigation |
|------|------------|
| Marquez schema drift vs Atlas entities | Shared IDs/namespaces; rdbms_* qualifiedNames ↔ OL dataset names |
| Running full Marquez JVM + UI cost | Optional process; API-only in CI; web for demos |
| Impala/Airflow hook sprawl | Prefer polyglot/sigint emission + one OL ingress |
| Treating Marquez as SoR | Explicit: Atlas + OL event store own truth; Marquez is validator/UI |

## Ops note

Submodule add used `env -u LD_LIBRARY_PATH` for git+ssh under devenv (glibc clash).
