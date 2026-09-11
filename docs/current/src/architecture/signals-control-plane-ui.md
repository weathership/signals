# Signals Control Plane UI (`signals-ui`)

**Status:** Architecture plan (repo + stack decisions locked)  
**Date:** 2026-08-10  
**Repo:** `git@github.com:weathership/signals-ui.git`  
**Signals path:** `components/signals-ui` (git submodule)  
**Related:** [OpenLineage + Atlas](./openlineage-atlas.md), [YuniKorn](../components/yunikorn.md), [MiNiFi sentinels](../../components/signals-protocol/specification/operations/minifi_sentinels.md), [signals-federation Zarf](../infrastructure/signals-federation-zarf.md)

## Thesis

**`signals-ui` is the primary backplane UI for Signals.** Admission,
queues, and process visibility go through YuniKorn; operators open
`:9889`.

1. **Superset of stock yunikorn-web** — YK REST used in
   `rch-yunikorn-web`, plus Signals views (lineage, sentinels,
   federated surfaces).
2. **Isolated submodule** — developed in `weathership/signals-ui`, vendored
   into Signals as `components/signals-ui` (same pattern as other components).
3. **Idiomatic Rust for the service** — no Node.js runtime in production.
   **Axum** ([tokio-rs/axum](https://github.com/tokio-rs/axum)); Askama HTML.
   Visual law: **Keiretsu** (Atelier) + **Cloudera** logo for brand continuity
   with Atelier/Aegir; dark + light.
4. **Federation overwatch** — MiNiFi sentinels, OTel, Atlas OL lineage, and
   engine discovery sit beside YK views in one process.
5. **Engine required** — `/readyz` is `zndx.engine.v1.Engine/Status` with
   `capability=scheduler` healthy. `SIGNALS_UI_ALLOW_NO_YK=1` is chrome-only
   lab (skip Status). YuniKorn REST is private to the engine.

```
                    ┌──────────────────────────────────────────────┐
                    │  signals-ui  (Rust service · Keiretsu UI)    │
                    │  = yk-web capabilities  ∪  Signals value-add │
                    └────────┬──────────┬──────────┬───────────────┘
           YK /ws/v1/*       │  C2/OTel │  Atlas   │  discovery
                             ▼          ▼          ▼
                      YuniKorn     MiNiFi     Atlas :21010
                      (admission)  sentinels  /api/v1 + /api/atlas
```

---

## 0. Repository and process

| Item | Decision |
|------|----------|
| Upstream repo | `git@github.com:weathership/signals-ui.git` |
| Signals submodule | `components/signals-ui` |
| Language (service) | **Rust** (edition 2021+, idiomatic: `axum` / `tower` / `tokio` / `reqwest` / `serde`) |
| Presentation | Rust-native UI preferred (**Leptos** or **Dioxus** + Trunk, or server-rendered HTML via Askama/Maud + progressive enhancement). **No Node service.** Asset pipeline must not require a long-lived Node runtime in devenv/prod. |
| Theme | Keiretsu CSS + Kumo token ramp (vendored from Atelier / `cldr-design-template`); `data-theme="keiretsu"` + `data-mode="dark\|light"` |
| Port policy | **9889** default (`SIGNALS_UI_BIND`); yk-web muscle memory. |
| YuniKorn | **Required** when stack is up (`SIGNALS_YK_API_URL`). Primary backplane. |
| Brand logos | Pluggable packs (`SIGNALS_UI_BRAND`): cloudera (default) · weathership · custom · `SIGNALS_UI_BRAND_DIR` |
| Theme | Keiretsu dark/light (fixed; not brand-switched) |
| Product identity | **Signals** (brand-agnostic copy/vars) |
| Auth | Lab: open or simple; prod: Cloudflare ZT in front ([identity-and-access](./identity-and-access.md)) |

### Submodule lifecycle (Signals monorepo)

```bash
# once repo exists and has an initial commit
git submodule add git@github.com:weathership/signals-ui.git components/signals-ui
# devenv: process + task to build release binary
# cargo build --release -p signals-ui
```

Do **not** embed a large Node monorepo under signals root for this product.

---

## 1. Strict yunikorn-web superset

### 1.1 Capability catalog (must implement — parity bar)

Reference: `~/local/src/asf/rch-yunikorn-web/` (Angular; port 9889; hash routes).

| Stock route | Capability | signals-ui requirement |
|-------------|------------|------------------------|
| `/dashboard` | Cluster overview, history charts | **Required** parity |
| `/applications` | Apps by partition/queue; allocations; state log | **Required** parity |
| `/queues`, `/queues-v2` | Queue tree, resources, properties/templates | **Required** (both layouts or unified equivalent covering all data) |
| `/nodes` | Capacity, allocated/occupied/available, foreign allocs, search | **Required** parity |
| `/status` | Scheduler healthchecks | **Required** parity |
| Charts | Donut/area/bar as used by dashboard/nodes | **Required** functional equivalent (not pixel clone) |
| Error surface | API failure UX | **Required** |

Parity means: an operator who today uses yk-web can complete the **same tasks**
against the same YuniKorn without opening Angular. Layout may differ (Keiretsu);
**data and actions** may not.

### 1.2 YK REST surface (must cover — contract suite)

From yk-web `SchedulerService` + health/utilization:

| Method | Path | Use |
|--------|------|-----|
| GET | `/ws/v1/clusters` | Cluster list |
| GET | `/ws/v1/partitions` | Partitions |
| GET | `/ws/v1/partition/{p}/queues` | Queue tree + resources/templates |
| GET | `/ws/v1/partition/{p}/queue/{q}/applications` | Apps, allocations, stateLog, times |
| GET | `/ws/v1/partition/{p}/nodes` | Nodes + allocations + foreignAllocations |
| GET | `/ws/v1/history/apps` | App count time series |
| GET | `/ws/v1/history/containers` | Container count time series |
| GET | `/ws/v1/scheduler/node-utilizations` | Utilization buckets |
| GET | `/ws/v1/scheduler/healthcheck` | Health checks |

**Contract tests** live in `signals-ui`: golden JSON fixtures captured from
yk-web’s json-server (`json-db.json`) and/or live YK; Rust client deserializes
every field the Angular models used (see `src/app/models/*` in yk-web).

### 1.3 Superset (Signals value-add — after / with parity)

| Extension | Source | Notes |
|-----------|--------|-------|
| App ↔ sentinel ↔ engine | MiNiFi C2, Knative, tags | Overwatch |
| App ↔ OTel duration/stages | Collector / Tempo-compatible API | Uniform process proxy |
| App ↔ OpenLineage run | Atlas `/api/v1` | Semantic I/O lineage |
| History (data products) | Catalog + `dev.signals.dataproduct.updated` | Agent-facing quality / lineage / delta |
| Lineage browse (table/column) | Atlas OL | Facet inside a product, not the top-line menu |
| Sources / schema / versions | Atlas-enriched OL | Same |
| Federated engine board | Discovery + `zndx.engine.v1` | Peers |
| OTel routing views | Collector config + traces | S04 RCA entry |

**Rule:** YK parity is not optional “phase debt.” Value-add routes may ship
behind flags, but **YK surface area ships complete** before declaring
yk-web replaced.

### 1.4 Deliberately discarded (from stock yk-web)

| Stock | signals-ui |
|-------|------------|
| Angular 13 + Node toolchain as runtime | Rust service; no Node runtime |
| Material / ad-hoc SCSS | Keiretsu + Kumo |
| json-server as product default | Live YK (fixtures only for tests) |
| Scheduler-only product | Control-plane product (superset) |

---

## 2. Rust service architecture

### 2.1 Crate layout (proposed)

```
signals-ui/                     # weathership/signals-ui
  Cargo.toml                    # workspace
  crates/
    signals-ui/                 # binary: axum server
    signals-ui-yk/              # YK REST client + models (parity with yk-web models)
    signals-ui-atlas/           # Atlas /api/v1 + /api/atlas clients
    signals-ui-otel/            # OTel query helpers
    signals-ui-core/            # config, error, correlation ids
  assets/                       # keiretsu.css, kumo tokens, static
  ui/                           # Leptos/Dioxus app or templates (if split)
  tests/
    yk_parity/                  # contract tests vs fixtures + live YK
  README.md
```

### 2.2 Runtime responsibilities

| Concern | Implementation |
|---------|----------------|
| HTTP server | `axum` + `tower-http` (trace, cors, compression, static) |
| YK proxy/client | Typed client; optional reverse-proxy path for raw `/ws/v1/*` |
| BFF merge API | e.g. `GET /api/signals/v1/processes/{id}` → YK + OTel + OL |
| Config | env + optional HOCON/YAML; `SIGNALS_YK_API_URL`, `SIGNALS_ATLAS_HTTP_*`, OTel, C2 |
| Health | `/healthz` (liveness), `/readyz` (Engine/Status scheduler healthy) |
| Metrics | Prometheus `/metrics` (idiomatic for control plane) |

### 2.3 Presentation options (choose in Phase 0 spike)

| Option | Pros | Cons |
|--------|------|------|
| **A. Leptos (CSR/SSR) + Trunk** | Full Rust, reactive, one language | WASM size; learning curve |
| **B. Dioxus** | Fullstack Rust story | Ecosystem younger |
| **C. Axum + Askama/Maud + HTMX** | Simple, tiny, very idiomatic ops UI | Less “app-like” interactivity |
| **D. Axum serves prebuilt WASM/static** | Clear split | Two-step build |

**Recommendation:** spike **A or C** in week one; pick on binary size, charting
story, and team velocity. Charts: prefer Rust-friendly (e.g. plotters → SVG,
or lightweight canvas) over pulling a Node chart stack.

Keiretsu/Kumo remain **CSS tokens**, not a JS theme runtime.

---

## 3. UI standards (Keiretsu + Kumo)

Canonical references (do not invent a third palette):

| Asset | Location |
|-------|----------|
| Keiretsu CSS ramp | Atelier `ui/src/styles/theme-keiretsu.css` (upstream: `cldr-design-template`) |
| Kumo ramp values | Atelier `ui/src/theme/kumo.ts` (restated as CSS vars in signals-ui) |
| Color mode | `data-mode="dark" \| "light"` independent of `data-theme="keiretsu"` |

### Laws

1. **Elevation is lightness** — canvas &lt; base &lt; elevated  
2. **Accents on accent duty only** — brand for primary/link/focus  
3. **Contrast band** — text 10–13:1 on surfaces  

Default **dark**; full **light** parity required.

---

## 4. Atlas backplane (feeds superset lineage)

Closing Marquez-native gaps remains **Atlas enrichment**; `signals-ui` is a
client. See [openlineage-atlas.md](./openlineage-atlas.md).

| Gap | Atlas work | signals-ui view |
|-----|------------|-----------------|
| Column lineage | Facet → `/api/v1/column-lineage` | Lineage module |
| Schema / fields | Facets + `rdbms_column` | Dataset detail |
| Versions | Event fingerprint / entity version | History tabs |
| Sources | Upsert `lineage_sources` | Sources catalog |
| Duration / last-N | OL pairs **and** YK/OTel merge (§5) | Process / run bars |

Native Atlas `/api/atlas/v2/lineage` remains available for governance graphs.

---

## 5. Sentinels + YK as uniform process proxy

| Signal | Source | UI |
|--------|--------|-----|
| Admission / queues | YuniKorn | YK-superset views |
| Claim / scale-to-zero | Knative + YK app state | Sentinel + app detail |
| C2 health | MiNiFi | Sentinels module |
| Duration / stages | OTel | Merged process timeline |
| Semantic I/O | OpenLineage → Atlas | Lineage module |

```
duration_display = coalesce(duration_ol, duration_otel, duration_yk)
correlation: openlineage.runId · yunikorn.applicationId · otel.trace_id · signals.workload_id
```

Standardize keys in signals-protocol; `signals-ui` BFF implements merge.

---

## 6. Phased delivery

### Phase 0 — Repo + Rust skeleton

- [ ] Create `weathership/signals-ui` (Apache-2.0 or project license as decided)
- [ ] Workspace: axum binary, `signals-ui-yk` client, health, config
- [ ] Vendor Keiretsu CSS; dark/light shell page
- [ ] Add submodule `components/signals-ui` in Signals
- [ ] devenv process + `cargo` task; document port
- [ ] **Spike:** Leptos vs Askama+HTMX decision recorded in signals-ui README

### Phase 1 — YK-web **complete** parity (superset base)

- [ ] All §1.1 routes/capabilities
- [ ] All §1.2 REST clients + deserialization of yk-web model fields
- [ ] Contract tests vs `json-db.json` fixtures from rch-yunikorn-web
- [ ] Live YK e2e in lab when scheduler is up
- [ ] **Acceptance:** side-by-side checklist vs Angular yk-web; no missing operator task

### Phase 2 — Superset: process proxy + Atlas lineage

- [ ] Correlation + merged duration API
- [ ] Sentinel + OTel modules
- [ ] Lineage (table; column when Atlas ready)
- [ ] Jobs/datasets/events/sources views (Atlas `/api/v1`)

### Phase 3 — Atlas depth (backplane; may be parallel in `components/atlas`)

- [ ] Column lineage, fields, versions, sources enrichment
- [ ] OL duration last-N from event pairs
- [ ] signals-ui consumes enriched APIs

### Phase 4 — Production federation

- [ ] ZT auth, namespace tenancy
- [ ] OL ↔ Atlas entity projection
- [ ] Zarf/package packaging for air-gap control plane

---

## 7. Non-goals

| Non-goal | Why |
|----------|-----|
| Node.js service or Node-based devenv dependency for signals-ui | Explicit departure |
| Investing in or owning Angular yunikorn-web | Apache YK focuses on core features; stock SPA may ship disabled. Not Keiretsu. **Optional lab exposure** is OK while our pin still includes it enabled |
| Growing Marquez-web into control plane | Wrong ownership; temporary validator only |
| Reimplementing YuniKorn scheduling | Client of `/ws/v1` only |
| Subset “dashboard-only” replacement of yk-web | Must be **strict superset** |

---

## 8. Acceptance criteria

### YK-web replacement (hard gate)

- [ ] Every yk-web operator task works in signals-ui against live YK  
- [ ] Contract suite green for all §1.2 endpoints  
- [ ] Documented mapping: yk-web screen → signals-ui route  

### Superset

- [ ] At least one Signals-only module (sentinels or lineage) shippable  
- [ ] Merged duration for a process with YK+OTel and optional OL  

### Platform

- [ ] Single Rust binary (or small set of crates) in release builds  
- [ ] Keiretsu dark + light  
- [ ] Submodule builds under Signals devenv/CI  

---

## 9. Immediate next actions

1. **Create** `weathership/signals-ui` empty repo + Apache-2.0 (or project) license  
2. **Scaffold** Axum hello + YK client crate + Keiretsu static shell  
3. **Import** yk-web `json-db.json` as fixtures; first contract test (`/ws/v1/partitions`)  
4. **Submodule add** into Signals when skeleton builds  
5. **Presentation spike** (Leptos vs HTMX) ≤ 1 week, then freeze  
6. Parallel in Atlas: column-lineage facet spike (feeds Phase 2–3)

---

## Related

- OpenLineage SoR: [openlineage-atlas.md](./openlineage-atlas.md)  
- Federation Zarf: [signals-federation-zarf.md](../infrastructure/signals-federation-zarf.md)  
- Sentinels: `components/signals-protocol/specification/operations/minifi_sentinels.md`  
- YK web reference (capability only): `~/local/src/asf/rch-yunikorn-web/`  
- Theme: Atelier `ui/src/styles/theme-keiretsu.css`, `ui/src/theme/kumo.ts`  
