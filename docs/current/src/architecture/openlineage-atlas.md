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
| OL HTTP ingest | **Atlas OL extension** | e.g. `POST /api/v1/lineage` |
| Marquez-compatible read | **Atlas OL extension** | Subset marquez-web needs |
| Marquez **server** + **Postgres schema** | **Not deployed** | Would dual-write SoR; rejected |
| Marquez **web UI** | Optional process | Points at Atlas OL API only |
| Heavy lineage analytics | **FDW → Impala → Kudu** | Atlas projections / OL tables on Kudu |

**Hard rule:** do **not** create a `marquez` database or run stock Marquez API as
a second catalog. Submodule `components/marquez` supplies **UI + contract
tests** (and minimal diffs only if the Atlas facade needs them).

## Why no Marquez DB

Stock Marquez owns its own Flyway schema and becomes a **second system of
record**. That fights:

1. Atlas as governance SoR  
2. A single composite graph (Aegir/Gaius already target AGE)  
3. Scale-out via **FDW / Kudu**, not by cloning OL tables into Marquez’s layout  

The correct convergence is **extend Atlas’s store and API** so any
OL-consuming UI (Marquez-web or third-party) talks only to Signals.

## Deployment model (one process, one port)

```
Producers (Flink OL, Airflow, polyglot, sigint, …)
        │
        ▼
 Atlas :21010  (single process)
   ├─ /api/atlas/*     # governance — existing clients, zero changes
   └─ /api/v1/*        # OL ingest + Marquez-compat read (extension)
        │
        ▼
 signals Postgres :5455
   ├─ Atlas AGE graph (entities, classifications, OL Job/Run/Dataset)
   └─ optional Kudu projections (FDW scale path)

 marquez-web :3000  ── default stack (always with devenv up); proxies /api/v1 → Atlas
```

Path prefixes do not collide. marquez-web only forwards `/api/v1` (and
`/api/v2beta`); it never needs to own the host. No second API process, no
second port for SoR HTTP. Marquez-web is **not optional** — it is part of the
default process graph for every `devenv up` / `devenv up -d`.

### Non-goals (rejected)

| Approach | Why rejected |
|----------|--------------|
| Stock Marquez API + Flyway DB | Second system of record |
| Python/FastAPI OL facade beside Atlas | Vestigial the day Atlas serves `/api/v1`; dual surface, dual deploy |
| Separate OL port “until Atlas is ready” | Encourages the throwaway; ship the Atlas extension instead |

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
| Marquez-web / OL HTTP clients | Talk only to Atlas `/api/v1/*` |

## Marquez in devenv

| Piece | Role |
|-------|------|
| `components/marquez` | Source submodule (UI + API contract reference) |
| `languages.javascript` | `directory = components/marquez/web`; `npm.install.enable` (enterShell) |
| `tasks.marquez:build-web` | **Before** `devenv:processes:marquez-web` — npm + webpack; turn-key `devenv up [-d]` |
| `processes.marquez-web` | **Default stack** — always starts with `devenv up`; `:3000`, depends on Atlas |
| `SIGNALS_OL_API_HOST` / `PORT` | Atlas (`:21010`); UI proxies `/api/v1` there via `setupProxy.js` |

There is **no** `marquez:db-init`, **no** `marquez` PG database, **no**
`processes.marquez-api`, **no** Python OL side service.

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
| **M2** | **Atlas webapp** OL extension: `POST /api/v1/lineage` + Marquez-compat `GET /api/v1/*` writing Job/Run/Dataset (and event log) into signals PG/AGE — same process as governance |
| **M3** | Flink dual-path tests green (OL → Atlas `/api/v1`; Atlas clients still healthy) |
| **M4** | Kudu/FDW projections for scale; logical backup via DataFusion Parquet; Gaius/Aegir → Signals |

M2 lives in `components/atlas` (`OpenLineageServlet` on `/api/v1/*`), not in
Python. Broader federation (discovery of Atlas/Ranger, OIP, external peers such
as Metabase) is documented under
[Signals protocol core](./signals-protocol-core.md).

## Related

- [Signals protocol core](./signals-protocol-core.md) — submodule, discovery, OIP  
- Scratch: `docs/scratch/2026-08-08/145328_marquez-composite-schema-direction.md`  
- Scratch: `docs/scratch/2026-08-08/151502_no-marquez-db-composite-sor.md`  
- Aegir: `gateway/marquez.py` (contract/shape reference only — not deployed here)  
- Gaius: `gaius.hx.lineage` (event + AGE labels reference)  
- FDW: `components/impala_fdw` (scale path for projection tables)  
