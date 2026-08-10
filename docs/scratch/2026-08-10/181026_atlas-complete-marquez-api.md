# Atlas complete Marquez-compatible OpenLineage API

## Doctrine (user)

Atlas must support the **complete** Marquez OpenLineage API. Marquez is the
**validation harness** (UI + request paths), not a second system of record.

## What changed

### Atlas (`components/atlas`)

- `OpenLineageServlet` — full router for Marquez `/api/v1/*` and `/api/v2beta/*`
  (namespaces, jobs, runs, datasets, tags, events, lineage, column-lineage,
  search, stats, sources, ingest, run transitions, entity tags).
- `OpenLineageStore` — AGE graph + relational tables:
  `lineage_events`, `lineage_namespaces`, `lineage_tags`, `lineage_entity_tags`,
  `lineage_sources`.
- `web.xml` — maps `/api/v1/*` and `/api/v2beta/*`.
- `AtlasSecurityConfig` — permits both prefixes (lab; ZT/IdP in prod).

### Docs

- `docs/current/src/architecture/openlineage-atlas.md` — complete API doctrine;
  Marquez as validator.
- `docs/current/src/components/marquez.md` — UI + acceptance probe.

## Acceptance (lab)

After rebuild + Atlas restart, UI-critical paths return 200 (empty collections OK):

- `/api/v1/{health,namespaces,tags,jobs,events/lineage,stats/*,search,sources}`
- `/api/v2beta/search/{jobs,datasets}`
- Marquez-web proxy `:21011` → Atlas

Seed: `POST /api/v1/lineage` RunEvent → jobs/datasets/events/lineage visible.

## Ops note

Killing Atlas outside the process manager may leave the native daemon in a
partial state; prefer `devenv processes` restart when available, or start
Atlas with the same classpath as `devenv.nix` processes.atlas.
