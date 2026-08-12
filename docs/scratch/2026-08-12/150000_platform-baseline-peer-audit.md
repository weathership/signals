# Platform baseline audit — peer-project dependency readiness

**Date:** 2026-08-12  
**Audience:** Signals foundation + Gaius / Aegir / Atelier (and future peers)  
**Context:** System-level group control (`signals.target` + peer units) will
assume a **stable foundation**. This audit scores that foundation as of trunk
`03e41bf`+ (M3 Eventing landed).

---

## Executive summary

| Layer | Peer-dependable today? | Grade |
|-------|------------------------|-------|
| Host data + governance (PG, KDC, RustFS, Atlas, Ranger, Kudu, Impala) | **Yes** (lab, after `just up`) | **A−** |
| Control UI (signals-ui + YK) | **Yes** | **A−** |
| Federation schedule (YuniKorn + Knative Serving) | **Yes** | **A−** |
| Platform Metaflow metadata + RustFS profile | **Yes** (profile file) | **B+** |
| Platform Airflow 3 + schedule path | **Yes** (lab LocalExecutor) | **B+** |
| Event fabric (Knative Eventing → Airflow) | **Yes** (default, verified smoke) | **B+** |
| Turn-key lifecycle for systemd group | **Partial** | **B** |
| Versioned peer contract / discovery | **Weak** | **C+** |
| Air-gap / Zarf completeness (Eventing images) | **Partial** | **C** |

**Bottom line:** Peers can **depend on Signals as foundation** for Metaflow
service URL, Airflow API, CE Broker, YK queues, Atlas OL, and lab data plane —
**if** they order after a **readiness gate** (not merely process start), use
**published endpoints**, and treat lab credentials as lab-only. Systemd
`signals.target` is the right next packaging layer; the platform surface is
coherent enough to put under it.

---

## Live snapshot (this host)

| Surface | Status |
|---------|--------|
| `devenv processes list` | **12/12 ready** (incl. kudu-*, impala-*, signals-ui) |
| `signals_stack_preflight` (no auto) | **critical plane OK** + Eventing Broker Ready |
| Metaflow `:30180/ping` | `pong` |
| Airflow `:30800/api/v2/version` | `3.1.7` |
| YuniKorn `:30080` | OK |
| Broker `signals-events/default` | Ready |
| Triggers (4) | Ready → `airflow-dag-trigger` |
| CE smoke | `signals_eventing_smoke` → **success** (M3) |

---

## Peer contract: what Gaius / Aegir / Atelier should consume

These are the **stable lab contracts**. Prefer env + profile files over hardcoding.

### 1. Lifecycle (foundation unit)

| Contract | Value |
|----------|--------|
| Start | `just up` or `devenv up -d` (WorkingDirectory = signals root) |
| Stop | **`just down`** (not bare `devenv processes down` — leaves PG on :5455) |
| Ready gate | `just stack-ready` exit 0 (or `/readyz` on signals-ui + stack-preflight) |
| Reset | `just stack-reset` |

**Systemd implication:** `Type=oneshot`/`notify` wrappers should wait for
`stack-ready`, not only for `devenv up -d` returning. Peers: `After=signals.service`
**and** a readiness probe on foundation (e.g. `ExecStartPost=` curl stack-ready
or signals-ui `/readyz`).

### 2. Identity & data plane

| Contract | Lab endpoint | Notes |
|----------|--------------|-------|
| Postgres | `127.0.0.1:5455` | **Lattice-owned** by signals; do not reuse |
| Kerberos | realm `DEV.VISTA.ZNDX.ORG`, host `$SIGNALS_KRB_HOST` | Auto on up; recovery `just bootstrap` |
| RustFS S3 | `http://127.0.0.1:9010` | Lab keys `rustfsadmin` / `rustfsadmin` |
| Impala HS2 | `$SIGNALS_KRB_HOST:21050` GSSAPI | Kudu-backed analytic path |
| Atlas HTTP | `http://127.0.0.1:21010` | OL SoR; Marquez-web `:21011` validator only |
| Ranger | `http://127.0.0.1:6080` | Lab install |

Port lattice (do not collide):

```text
5438 cybersec · 5444 gaius · 5455 signals · 5533 atelier · 5555 aegir · 5566 synth
```

### 3. Platform Metaflow

| Contract | Lab (node) | In-cluster |
|----------|------------|------------|
| Metadata | `http://127.0.0.1:30180` | `http://metaflow-service.metaflow.svc:8080` |
| Profile | `config/metaflow/platform.json` | copy / env overlay |
| Datastore | `s3://metaflow/metaflow` @ RustFS | bridge `signals-rustfs.metaflow.svc:9010` |
| K8s ns / SA | `metaflow` / `metaflow-task` | YK queues `root.{engine,signals,…}` |

**Peer action:** stop local Tilt Metaflow when joining platform; point
`METAFLOW_SERVICE_URL` + S3 endpoint at platform profile.

### 4. Platform Airflow

| Contract | Lab |
|----------|-----|
| UI / API | `http://127.0.0.1:30800` |
| Auth | Lab `admin`/`admin` → `POST /auth/token` → Bearer for `/api/v2` |
| Executor | **LocalExecutor** (lab); not multi-worker Celery |
| Smoke DAG | `signals_smoke` |
| Event DAG | `signals_eventing_smoke` |

**Peer action:** `airflow create` DAGs → platform `dags/` (ConfigMap path today);
schedule via `@schedule` **or** events below.

### 5. Event fabric (M3 — default, no Argo)

| Contract | Value |
|----------|--------|
| Broker | `signals-events/default` |
| Ingress (cluster) | `http://broker-ingress.knative-eventing.svc.cluster.local/signals-events/default` |
| Publish helper | `just events-publish <ce-type> '<json>'` |
| Sink | `airflow-dag-trigger` (JWT + dagRuns) |

**Standard CE types** (extend via sink `TYPE_DAG_MAP` / `Ce-Dagid`):

| type | Default DAG |
|------|-------------|
| `dev.signals.eventing.smoke` | `signals_eventing_smoke` |
| `dev.signals.smoke.trigger` | `signals_smoke` |
| `dev.metaflow.flow.finished` | `signals_eventing_smoke` |
| `dev.gaius.article.curate.requested` | `signals_eventing_smoke` |
| `dev.signals.sentinel.activated` | `signals_eventing_smoke` |

**Peer action:** replace Argo Events publish with CloudEvents to this Broker;
do not stand up Argo Workflows for production Metaflow on platform.

### 6. Federation schedule

| Contract | Value |
|----------|--------|
| YuniKorn REST | `http://127.0.0.1:30080` |
| Queues | `root.{default,aegir,atelier,gaius,signals,hermes}` |
| signals-ui | `http://127.0.0.1:9889` (`/readyz` requires YK) |

---

## Consistency strengths (keep these)

1. **Single entry:** `just up` / `devenv up -d` owns host graph + stack-ready path.
2. **Uniform critical plane** policy matches live preflight (incl. Eventing).
3. **Explicit non-goals:** no Marquez DB, no Argo, no engine-local Metaflow as SoR.
4. **Port lattice** prevents multi-devenv PG thrash.
5. **Eventing as default** gives peers one reactive path aligned with Airflow+Metaflow.
6. **Recipes** cover status/smoke for each platform slice (`metaflow-platform`,
   `airflow-platform`, `knative-eventing`, `airflow-eventing-smoke`).

---

## Gaps before peers hard-depend (priority ordered)

### P0 — Required for safe `signals.target` group control

| Gap | Risk | Recommendation |
|-----|------|----------------|
| **Readiness ≠ process start** | Peer starts while Metaflow/Airflow/Eventing still warming | Foundation `ExecStartPost=` / wrapper: loop `just stack-ready` until 0; peers wait on that |
| **`devenv processes down` orphans PG** | Next foundation start fails `strictPorts` | Document **only** `just down` / stack-reset in systemd `ExecStop=` |
| **No versioned contract file** | Peers scrape docs; drift | Publish `config/platform/peer-contract.json` (endpoints, CE types, versions) + semver note in docs |
| **Lab credentials as defaults** | Accidental exposure if group runs on shared host | Secretspec / env for Airflow admin + RustFS; never bake into peer images |

### P1 — Solidify Metaflow production path

| Gap | Risk | Recommendation |
|-----|------|----------------|
| **`airflow create` → dags not automated** | Each peer invents ship path | One documented pipeline: generate DAG → ConfigMap/git-sync → platform Airflow |
| **LocalExecutor only** | Heavy multi-engine load | Document scale-up path (Celery/K8s executor) as platform change, not peer choice |
| **In-cluster vs node URLs** | Peers on host vs in-pod confuse endpoints | Keep dual URLs in `platform.json`; peers pick by placement |

### P2 — Air-gap / packaging

| Gap | Risk | Recommendation |
|-----|------|----------------|
| **Eventing images not in Zarf package** | Offline reinstall needs gcr + zarf ignore | Add Eventing to `signals-federation` package; drop agent ignore |
| **Serving packaged, Eventing live-applied** | Asymmetric converge | Extend federation converge T-states for Eventing + Broker Ready |

### P3 — Product polish for multi-engine

| Gap | Risk | Recommendation |
|-----|------|----------------|
| **CE → DAG map is lab-smoke heavy** | Real Gaius DAGs not wired | Per-engine trigger + DAG ids in peer-contract |
| **Broker client timeout** | Publish helper may 000 while delivery OK | Document poll-Airflow pattern; optional async publish |
| **No signals-protocol discovery** | Manual URL config | Optional: expose contract via Atlas or small HTTP `/platform/v1` on signals-ui |
| **systemd units not checked in** | Drift between hosts | Land sample units under `infra/systemd/` when ready |

---

## Grades for systemd group readiness

| Question | Answer |
|----------|--------|
| Can `signals.service` be the foundation unit? | **Yes** — `WorkingDirectory` + `just up` / `just down` |
| Can peers `After=signals.service`? | **Yes, with readiness wait** — soft `Wants=` alone is insufficient |
| Will Eventing be available when peers start? | **Yes if** foundation runs stack-ready (auto Eventing) before reporting ready |
| Shared host multi-devenv OK? | **Yes** if peers keep lattice ports and only Signals owns :5455 |
| Air-gap lab OK? | **Partial** — Serving/YK yes; Eventing needs gcr until Zarf’d |

---

## Recommended peer integration checklist

1. **Order:** `After=signals.service` + wait for `http://127.0.0.1:9889/readyz` **and** `just stack-ready` (or a thin `signals-ready.service` oneshot).
2. **Metaflow:** adopt `config/metaflow/platform.json` (or env equivalent); disable local metadata service in platform mode.
3. **Triggers:** publish CE to platform Broker; do not add Argo Events.
4. **Compute:** K8s tasks → RKE2 + YK queue `root.<peer>`; never bypass YK for production steps.
5. **Lineage:** Atlas OL only; no peer Marquez DB.
6. **Do not** bind Postgres on :5455 or RustFS on :9010 in peer devenvs.

---

## Suggested next engineering steps (after this audit)

1. **`signals-ready` oneshot** used by systemd and peers (wraps stack-ready + exit codes).
2. **`config/platform/peer-contract.json`** + short mdbook “Peer integration” page.
3. **systemd unit samples** under `infra/systemd/` matching `build/2026-08-12-0812_signals-services.md`.
4. **Zarf Eventing** into signals-federation (close air-gap gap).
5. **Documented `airflow create` ship path** for one real Gaius/Aegir flow.

---

## Related

- `docs/current/src/architecture/stack-critical-plane.md`
- `docs/current/src/architecture/metaflow-platform.md` (M0–M3)
- `config/metaflow/platform.json`
- `config/k8s/eventing/`
- `build/2026-08-12-0812_signals-services.md` (systemd group direction)
