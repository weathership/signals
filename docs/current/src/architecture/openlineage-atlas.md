# OpenLineage + Atlas (Signals system of record)

Signals is the **system of record** for governance **and** OpenLineage-shaped
runtime lineage for consumers (Aegir, Gaius, and direct Signals users). One
deploy. One Postgres. Scaling of heavy projection/query via **Impala FDW /
kudu_scan** — not a second Marquez database.

## Doctrine

| Concern | Authority | Notes |
|---------|-----------|--------|
| Governance (types, classifications, policies) | **Atlas** on `signals` PG + AGE | Existing Atlas clients **unchanged** |
| Runtime lineage (Job / Run / Dataset, facets) | **Same Atlas/AGE store** (composite schema) | OL types + edges additive |
| OL HTTP ingest | **Atlas OL extension** | `POST /api/v1/lineage` |
| Marquez-compatible API | **Atlas OL extension — complete** | Full Marquez `/api/v1/*` + needed `/api/v2beta/*` |
| Marquez **server** + **Postgres schema** | **Not deployed** | Would dual-write SoR; rejected |
| Marquez **web UI** | Default-stack process | **Validation harness** for API completeness |
| Heavy lineage analytics | **FDW → Impala → Kudu** | Atlas projections / OL tables on Kudu |

**Hard rule:** do **not** create a `marquez` database or run stock Marquez API as
a second catalog. Submodule `components/marquez` supplies **UI + contract
reference** (and minimal diffs only if the Atlas facade needs them).

### Marquez as validator (not SoR)

Atlas must implement the **complete** Marquez OpenLineage API surface so that:

1. **Marquez-web** renders real content (jobs, datasets, events, search, stats, tags, lineage graphs).
2. **Marquez API contract tests** (and UI request paths under `web/src/store/requests/`) can be pointed at Atlas as an acceptance suite.
3. Any OpenLineage-shaped client (Flink, Airflow, polyglot) talks only to Signals.

Empty collections are valid when no data exists; **404 on an implemented route
shape is not**. The acceptance bar is: every path Marquez UI calls returns a
status and JSON body Marquez-shaped clients accept.

## Why no Marquez DB

Stock Marquez owns its own Flyway schema and becomes a **second system of
record**. That fights:

1. Atlas as governance SoR  
2. A single composite graph (Aegir/Gaius already target AGE)  
3. Scale-out via **FDW / Kudu**, not by cloning OL tables into Marquez’s layout  

The correct convergence is **extend Atlas’s store and API** so any
OL-consuming UI (Marquez-web or third-party) talks only to Signals.

## Deployment model (one SoR process; UI on adjacent port)

```
Producers (Flink OL, Airflow, polyglot, sigint, …)
        │
        ▼
 Atlas :21010  (single SoR process)
   ├─ /api/atlas/*     # governance — existing clients, zero changes
   ├─ /api/v1/*        # complete Marquez-compat OL API + ingest
   └─ /api/v2beta/*    # search jobs/datasets (OpenSearch-shaped; AGE-backed)
        │
        ▼
 signals Postgres :5455
   ├─ Atlas AGE graph (entities, classifications, OL Job/Run/Dataset)
   ├─ lineage_events / lineage_tags / lineage_namespaces / lineage_sources
   └─ optional Kudu projections (FDW scale path)

 marquez-web :21011  ── default stack; port = Atlas HTTP + 1; proxies /api/v1 + /api/v2beta → Atlas
```

Path prefixes do not collide. marquez-web only forwards `/api/v1` and
`/api/v2beta`; it never needs to own the SoR host. No second API process, no
second SoR HTTP port. Marquez-web is **not optional** — it is part of the
default process graph for every `devenv up` / `devenv up -d`, and the primary
human-facing proof that the Atlas OL API is complete.

**Port rule:** `MARQUEZ_WEB_PORT = SIGNALS_ATLAS_HTTP_PORT + 1` (defaults
`21010` / `21011`). Do not bind Marquez on `:3000` — that range is for
ad-hoc local frontends.

### Non-goals (rejected)

| Approach | Why rejected |
|----------|--------------|
| Stock Marquez API + Flyway DB | Second system of record |
| Python/FastAPI OL facade beside Atlas | Vestigial the day Atlas serves `/api/v1`; dual surface, dual deploy |
| Separate OL port “until Atlas is ready” | Encourages the throwaway; ship the Atlas extension instead |
| Subset-only Marquez API | UI empty / invalid; fails completeness validation |

Reference implementations elsewhere (Aegir `gateway/marquez.py`, Gaius
`hx.lineage`) inform **graph shape and contract tests**. They are not
deployed as Signals product API.

## Atlas client compatibility

| Client | Constraint |
|--------|------------|
| Atlas REST v2 (`/api/atlas/*`) | **No breaking changes** |
| rdbms_* / classifications | Additive only |
| AGE labels | New OL labels **additive** |
| Native Atlas lineage GUI | Continues on existing lineage APIs |
| Marquez-web / OL HTTP clients | Talk only to Atlas `/api/v1/*` (+ v2beta search) |

## Marquez API surface on Atlas

Implemented in `components/atlas` (`OpenLineageServlet` + `OpenLineageStore`):

| Area | Paths (representative) |
|------|------------------------|
| Health | `GET /api/v1/health` |
| Namespaces | `GET/PUT/DELETE /api/v1/namespaces[/{ns}]` |
| Jobs | `GET /api/v1/jobs`, `GET/PUT/DELETE .../namespaces/{ns}/jobs[/{job}]` |
| Runs | `GET .../jobs/{job}/runs`, `GET /api/v1/jobs/runs/{id}`, facets, start/complete/fail/abort |
| Datasets | `GET/PUT/DELETE .../namespaces/{ns}/datasets[/{ds}]`, versions |
| Tags | `GET/PUT /api/v1/tags[/{name}]`, entity/field tag attach/detach |
| Events | `GET /api/v1/events/lineage` |
| Lineage | `GET/POST /api/v1/lineage`, `GET /api/v1/column-lineage`, `GET /api/v1/runlineage/upstream` |
| Search | `GET /api/v1/search`, `GET /api/v2beta/search/jobs`, `.../datasets` |
| Stats | `GET /api/v1/stats/{lineage-events,jobs,datasets,sources}` |
| Sources | `GET/PUT /api/v1/sources[/{name}]` |
| Ingest | `POST /api/v1/lineage` (OpenLineage RunEvent) |

Store: AGE graph `signals_ol` (Job / Run / Dataset) plus relational
`lineage_events`, `lineage_namespaces`, `lineage_tags`, `lineage_entity_tags`,
`lineage_sources` on the same Postgres database as Atlas.

## Marquez in devenv

| Piece | Role |
|-------|------|
| `components/marquez` | Source submodule (UI + API contract reference) |
| `languages.javascript` | `directory = components/marquez/web`; `npm.install.enable` (enterShell) |
| `tasks.marquez:build-web` | **Before** `devenv:processes:marquez-web` — npm + webpack; turn-key `devenv up [-d]` |
| `processes.marquez-web` | **Default stack** — always starts with `devenv up`; **`:21011`** (Atlas + 1), depends on Atlas |
| `SIGNALS_OL_API_HOST` / `PORT` | Atlas (`:21010`); UI proxies `/api/v1` + `/api/v2beta` there via `setupProxy.js` |
| `MARQUEZ_WEB_PORT` | Override UI bind (default `SIGNALS_ATLAS_HTTP_PORT + 1`) |

There is **no** `marquez:db-init`, **no** `marquez` PG database, **no**
`processes.marquez-api`, **no** Python OL side service.

### Validation loop

```bash
# After atlas:build + restart atlas process:
curl -sS http://127.0.0.1:21010/api/v1/health
curl -sS http://127.0.0.1:21010/api/v1/tags
curl -sS http://127.0.0.1:21010/api/v1/jobs
curl -sS 'http://127.0.0.1:21010/api/v1/events/lineage?limit=10'
curl -sS 'http://127.0.0.1:21010/api/v1/stats/lineage-events?period=DAY'
# UI: http://<node>:21011  (proxies to Atlas)
```

Seed via `POST /api/v1/lineage` with a standard OpenLineage RunEvent; jobs,
datasets, events, and lineage should appear in Marquez-web without a Marquez DB.

## Producer validation: Flink

Upstream **Apache Flink** is a first-class OpenLineage integration; Cloudera’s
stack already proves Flink → Atlas. Dual-path lab check:

| Path | Expectation |
|------|-------------|
| OpenLineage | Flink OL → Atlas OL ingest → visible in Marquez-web (via Atlas API) |
| Atlas | Entities / processes remain queryable via stock Atlas clients |

BDD `@tier-1` (planned): `features/platform/lineage_flink_ol.feature`.

## Phased delivery

| Phase | Deliverable |
|-------|-------------|
| **M0** | Submodule + this doctrine |
| **M1** | marquez-web **default stack** process + build-web (UI → Atlas `/api/v1`) |
| **M2** | **Atlas webapp** complete Marquez-compat `/api/v1/*` + `/api/v2beta/*` into signals PG/AGE |
| **M3** | Flink dual-path tests green (OL → Atlas `/api/v1`; Atlas clients still healthy) |
| **M4** | Kudu/FDW projections for scale; logical backup via DataFusion Parquet; Gaius/Aegir → Signals |

M2 lives in `components/atlas` (`OpenLineageServlet` on `/api/v1/*` and
`/api/v2beta/*`), not in Python. Broader federation (discovery of Atlas/Ranger,
OIP, external peers such as Metabase) is documented under
[Signals protocol core](./signals-protocol-core.md).

## Related

- [Signals protocol core](./signals-protocol-core.md) — submodule, discovery, OIP  
- [Marquez component](../components/marquez.md) — UI-only deploy, port rule  
- Scratch: `docs/scratch/2026-08-08/145328_marquez-composite-schema-direction.md`  
- Scratch: `docs/scratch/2026-08-08/151502_no-marquez-db-composite-sor.md`  
- Aegir: `gateway/marquez.py` (contract/shape reference only — not deployed here)  
- Gaius: `gaius.hx.lineage` (event + AGE labels reference)  
- FDW: `components/impala_fdw` (scale path for projection tables)  
