# Platform Metaflow (YK · Knative · Airflow)

**Status:** Architecture direction (platform-grade)  
**Date:** 2026-08-11  
**Scope:** **Signals-owned** ground-up Metaflow capability — not Gaius, not
Marquez. Any federated engine that integrates via
[signals-protocol](../components/signals-protocol.md) can consume it as a
platform service.  
**Submodule:** `components/metaflow` →
[`weathership/oss-metaflow`](https://github.com/weathership/oss-metaflow)
branch **`rch/devenv`** (custom line, same convention as other ASF/oss
components).  
**References:**

- Outerbounds [AWS K8s deployment](https://docs.outerbounds.com/engineering/deployment/aws-k8s/deployment/)
  (`eks_airflow` Terraform path preferred for us)
- Metaflow [Airflow scheduling](https://docs.metaflow.org/production/scheduling-metaflow-flows/scheduling-with-airflow)
  · Outerbounds [Airflow ops](https://docs.outerbounds.com/engineering/operations/airflow/)
- Outerbounds [event triggering](https://docs.outerbounds.com/engineering/operations/event-triggering/)
  (stock stack uses **Argo Events**; we substitute **Knative Eventing**)

## Thesis

Signals provides a **platform Metaflow** so current and future engines
(Gaius, Aegir, Atelier, …) do not each stand up thrashing metadata services on
shared RKE2. Engine repos stay free to keep isolated Metaflow for solo
devenv; **this tree does not modify Gaius or Marquez**. Platform work lands
here: submodule patches, federation packaging, Airflow + Knative Eventing,
YuniKorn admission, signals-ui visibility.

With **YuniKorn + Knative Serving** already locked as the federation control
plane, Metaflow is a first-class **platform service**:

| Layer | Choice | Why |
|-------|--------|-----|
| Metadata service | Outerbounds metadata service + **shared PG** (platform DB) | Central run tracking for all engines |
| Artifact store | **RustFS** (S3 API) under `SIGNALS_DATA_ROOT` | Already platform object plane |
| Task compute | `@kubernetes` pods on RKE2 | Only compute layer Airflow integration supports |
| Pod scheduler | **YuniKorn** queues `root.{aegir,atelier,gaius,signals,hermes}` | Scarce GPU/CPU governance |
| Production DAG schedule | **Apache Airflow** (`airflow create`) | Already in Signals components; no Argo Workflows SoR |
| Event / reactive trigger | **Knative Eventing** → Airflow DAG trigger | Platform event fabric; matches Gaius need for trigger **without Argo** |
| UI | signals-ui **Applications** (+ Sentinels panel) | Workloads YK admits, including Metaflow task pods |

Stock Outerbounds prefers **Argo Workflows** when in doubt (full event
triggering). We deliberately take the **`eks_airflow` shape** and **close the
event gap with Knative Eventing**, not Argo Events / Argo Workflows.

## Submodule and customization line

| Field | Value |
|-------|--------|
| Path | `components/metaflow` |
| Remote | `git@github.com:weathership/oss-metaflow.git` |
| Branch | **`rch/devenv`** (created from upstream `master` pin; platform patches land here) |
| Init | `git submodule update --init components/metaflow` |

Platform-specific changes to Metaflow itself (Airflow event-bridge hooks,
Knative-friendly defaults, YK labels, devenv packaging) go on **`rch/devenv`**
in that repo — not as one-off patches only in Signals, and not by forking
work into Gaius.

## Isolation elsewhere (out of scope here)

Other products may still run **engine-local** Metaflow (Tilt metadata, private
PG/S3) for isolated devenv. That pattern is fine for those repos; **Signals
does not implement or maintain it**. Platform Metaflow is the shared SoR when
an engine opts into federation via signals-protocol.

### Why platform upgrade

| Isolation pain | Platform remedy |
|----------------|-----------------|
| Competing Tilt/Helm Metaflow on shared node | One Zarf/federation-aligned package + YK queues |
| ImagePull / registry thrash | Platform images in Zarf registry |
| No fair-share with sentinels / other engines | YK multi-tenant queues |
| Cron-only if we only use Airflow stock Metaflow triggers | Knative Eventing for external + inter-flow events |
| Opaque ops UI | signals-ui Applications · Queues · Status |

## Official stack vs Signals adaptation

```text
Outerbounds eks_argo (reference default)
  Metaflow service + S3 + EKS
  Argo Workflows  ←── steps
  Argo Events     ←── event triggering

Outerbounds eks_airflow (our base)
  Metaflow service + S3 + EKS
  Airflow         ←── steps as KubernetesPodOperator DAGs
  @schedule only  ←── stock Metaflow→Airflow (no native event trigger)

Signals platform (target)
  Metaflow service + RustFS + RKE2
  Airflow         ←── production DAGs (schedule + API-triggered runs)
  Knative Eventing←── event fabric (replace Argo Events role)
  YuniKorn        ←── schedule all Metaflow + sentinel pods
  Knative Serving ←── sentinels / scale-to-zero (already federation)
```

**Critical product fact:** Metaflow’s first-class
[event triggering](https://docs.metaflow.org/production/event-triggering) is
documented as **Argo Workflows only** today. Airflow docs state event-based
triggering is **not** supported via Metaflow’s Airflow integration (only
`@schedule` / cron). Gaius already showed that **application-level and
platform-level triggering** is enough for real product capability. We
**institutionalize** that as Knative Eventing → Airflow, rather than forking
Metaflow’s Argo-only path.

## Target architecture

```text
                    ┌─────────────────────────────────────┐
                    │  Producers                          │
                    │  CLI · MCP · Atlas OL · Sentinels · │
                    │  Engine gRPC · webhooks · cron      │
                    └──────────────┬──────────────────────┘
                                   │ CloudEvents
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  Knative Eventing                   │
                    │  Broker / Channel / Triggers        │
                    │  (types: metaflow.run.v1, …)        │
                    └──────────────┬──────────────────────┘
                                   │ Sink: Airflow REST / API
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  Apache Airflow (on RKE2, YK queue) │
                    │  DAGs from: python flow.py          │
                    │             airflow create dag.py   │
                    │  @schedule + event-triggered runs    │
                    └──────────────┬──────────────────────┘
                                   │ KubernetesPodOperator
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  RKE2 + YuniKorn                    │
                    │  Metaflow @kubernetes step pods     │
                    │  Queues root.{engine,signals,…}     │
                    └──────────────┬──────────────────────┘
                          ┌────────┴────────┐
                          ▼                 ▼
              ┌───────────────────┐  ┌──────────────────┐
              │ Metaflow metadata │  │ RustFS (S3)      │
              │ service + PG      │  │ artifacts/cards  │
              └───────────────────┘  └──────────────────┘
                          │
                          ▼
              ┌───────────────────┐
              │ signals-ui        │
              │ Applications ·    │
              │ Queues · Status   │
              └───────────────────┘
```

### Component notes

#### Metaflow metadata service

- Deploy as **platform** Deployment/Service (not engine Tilt thrash).
- Postgres: platform instance (`signals` or dedicated `metaflow` DB on lab PG
  5455 / production SoR) — **not** a second unmanaged store per engine.
- Expose: ClusterIP + NodePort or signals-ui/proxy for lab
  (`METAFLOW_SERVICE_URL`).
- Config profile (shared `~/.metaflowconfig` shape):

```json
{
  "METAFLOW_DEFAULT_METADATA": "service",
  "METAFLOW_SERVICE_URL": "http://metaflow-service.platform.svc:8080",
  "METAFLOW_DEFAULT_DATASTORE": "s3",
  "METAFLOW_DATASTORE_SYSROOT_S3": "s3://metaflow/metaflow",
  "METAFLOW_S3_ENDPOINT_URL": "http://rustfs.platform.svc:9010",
  "METAFLOW_KUBERNETES_NAMESPACE": "metaflow",
  "METAFLOW_AIRFLOW_KUBERNETES_CONN_ID": "kubernetes_default"
}
```

#### Airflow

- Run on RKE2 under YK (queue `root.signals` or `root.hermes` for control
  plane DAGs).
- Lab/platform pin: Airflow **3.1.7** (`components/airflow` chart); `cncf.kubernetes` provider for KPO.
- Metaflow steps → `KubernetesPodOperator` only (`@kubernetes`, not `@batch`).
- Deploy path: `python flow.py --with retry airflow create flow_dag.py` then
  ship DAG into Airflow `dags/` (Git-sync or ConfigMap pipeline).
- Time schedules: Metaflow `@schedule` as today.
- **Event runs:** Airflow REST `POST /api/v1/dags/{dag_id}/dagRuns` (or stable
  equivalent) invoked by Knative **SinkBinding / Service** — this is the
  platform “bring Airflow up to event-triggering spec.”

#### Knative Eventing (not Argo Events)

| Concern | Stock Outerbounds | Signals |
|---------|-------------------|---------|
| Event bus | Argo Events + Jetstream | Knative Broker (e.g. MT channel / Kafka later) |
| Ingest | Argo webhook | Knative Broker HTTP + domain sources |
| Filter | Argo sensors | `Trigger` filters on CloudEvent `type` / attributes |
| Action | Submit Argo Workflow | **Trigger Airflow DAG run** (+ optional ksvc) |

Example event types (illustrative):

- `dev.metaflow.flow.finished` — inter-flow chaining (`@trigger_on_finish` analogue)
- `dev.signals.sentinel.activated` — sentinel woke; start inspection flow
- `dev.gaius.article.curate.requested` — product CLI/MCP publish
- `dev.atlas.openlineage.runEvent` — optional OL-driven reactions

Emitter libraries: small platform helper (replace `ArgoEvent.publish`) that
POSTs CloudEvents to the Broker ingress. Gaius/CLI keep product APIs; they
**publish platform events** instead of talking Argo.

#### YuniKorn

- All Metaflow task pods and Airflow workers labeled into federation queues.
- signals-ui **Queues** flow already shows `root.*` capacity; **Applications**
  shows admitted apps (including Metaflow steps once scheduled).
- Avoid default-scheduler side channels for production steps.

#### Sentinels

- Remain Knative **Serving** (scale-to-zero).
- Eventing can wake work **and** start Metaflow DAGs when a sentinel signals
  readiness or C2 heartbeat thresholds — without conflating Serving and
  Workflow engines.

## Isolation vs platform (policy)

| Mode | When | Metaflow service | Scheduler | Trigger |
|------|------|------------------|-----------|---------|
| **Engine isolation** | Single-repo devenv, offline | Local Tilt/PG (Gaius-style) | Local / optional K8s | CLI/MCP |
| **Platform** | Shared RKE2, multi-engine | Platform metadata + RustFS | Airflow + YK pods | Knative Eventing + `@schedule` |

Engines opt into platform by setting Metaflow config profile to platform URLs
and deploying DAGs to platform Airflow. Isolation remains for unit hermeticity.

## Delivery phases

### M0 — Document + guardrails (this page)

- Architecture + non-goals; signals-ui Applications already frames YK workloads.

### M1 — Platform Metaflow service (**landed**)

| Artifact | Path |
|----------|------|
| Submodule | `components/metaflow` (`rch/devenv`) |
| K8s manifests | `config/k8s/metaflow/` |
| Bootstrap | `scripts/metaflow_platform_bootstrap.sh` · `just metaflow-platform` |
| Client profile | `config/metaflow/platform.json` |
| RustFS bucket | `metaflow` (devenv `rustfsBuckets`) |
| Lab URL | `http://127.0.0.1:30180/ping` (NodePort **30180**) |

Host PG (:5455) and RustFS (:9010) are bridged into `ns/metaflow` via
Service + Endpoints (`signals-postgres`, `signals-rustfs`).

### M2 — Airflow 3 on RKE2 (YK) (**landed**)

| Artifact | Path |
|----------|------|
| Submodule chart | `components/airflow/chart` (appVersion **3.1.7**) |
| Helm values | `config/k8s/airflow/values-signals.yaml` |
| Host PG bridge | `config/k8s/airflow/host-bridge.yaml` |
| Cross-ns RBAC | `config/k8s/airflow/rbac-metaflow.yaml` (KPO → `metaflow`) |
| Smoke DAG | `config/k8s/airflow/dags/signals_smoke_dag.py` |
| Bootstrap | `scripts/airflow_platform_bootstrap.sh` · `just airflow-platform` |
| Smoke | `just airflow-platform-smoke` |
| Lab URL | `http://127.0.0.1:30800` (NodePort **30800**, admin/admin) |

Shape: **LocalExecutor**, external PG (`airflow` DB on host :5455 via
hostNetwork **socat** proxy — devenv PG is loopback-only), no in-cluster
Bitnami Postgres/Redis. Fernet/JWT/API secrets persist under
`build/config/airflow-secrets.env`. Smoke DAG `signals_smoke` is live;
Metaflow `airflow create` DAGs ship next (same ConfigMap / dags path).
REST: AF3 `/api/v2` with JWT from `POST /auth/token`.

### M3 — Knative Eventing bridge (**landed**)

| Artifact | Path |
|----------|------|
| Eventing manifests (v1.23.0) | `zarf/federation/manifests/knative/eventing-*.yaml` (+ IMC + MT broker) |
| Platform ns | `signals-events` |
| Broker | `signals-events/default` (MTChannelBasedBroker / in-memory) |
| Sink | `airflow-dag-trigger` (CE HTTP → AF3 JWT + `/api/v2/dags/{id}/dagRuns`) |
| Triggers | smoke, metaflow.finished, gaius.curate, … |
| Bootstrap | `scripts/knative_eventing_bootstrap.sh` · `just knative-eventing` |
| Publish helper | `scripts/signals_events_publish.sh` · `just events-publish` |
| Smoke | `just airflow-eventing-smoke` (CE → `signals_eventing_smoke` DAG) |

**No Argo.** Engines (Gaius/Aegir/…) and Metaflow finish hooks publish CloudEvents
to the Broker; Triggers filter by `type` and invoke Airflow. Zarf agent ignore
until Eventing images are packaged into signals-federation.

### M4 — Multi-engine consumers

- Gaius/Aegir/Atelier profiles point at platform Metaflow
- signals-ui Applications: show Metaflow run correlation (run id ↔ YK app id)
- OL: keep Atlas SoR; Metaflow cards remain UX, not second lineage SoR

## Critical plane membership

Metaflow (with YK, Knative, Airflow, RustFS, and host data services) is part of
the **uniform critical plane** for Signals — enforced by
`just stack-ready` / `signals:stack-ready`. See
[Critical plane](./stack-critical-plane.md).

## Non-goals

- **Touching Gaius, Marquez, or engine repos** from this workstream — engines
  adopt platform Metaflow on their schedule via config + protocol
- **Argo Workflows / Argo Events as SoR** — rejected for this platform path
- Nested Metaflow foreaches on Airflow (Airflow limitation) — avoid in platform
  DAGs or gate on Airflow version + design
- Conditional/recursive steps (Metaflow 2.18+) until Airflow support exists
- Marquez DB as Metaflow metadata (Atlas OL remains lineage SoR)

## Open design questions

1. **Airflow executor:** start `LocalExecutor` / `CeleryExecutor` vs full
   `KubernetesExecutor` (DAG volume sync cost on single-node lab).
2. **Event exactly-once:** Broker + Airflow dagRun `dag_run_id` idempotency keys
   from CloudEvent `id`.
3. **Namespace layout:** one `metaflow` ns vs per-engine namespaces for pods
   with YK queue labels only.
4. **UI:** Metaflow UI (Outerbounds) optional lab validation vs signals-ui only.

## Related

- [signals-federation Zarf](../infrastructure/signals-federation-zarf.md) — YK + Knative Serving
- [Airflow component stub](../components/airflow.md)
- [signals-ui Applications](./signals-control-plane-ui.md) — workloads surface
- Gaius Metaflow service (isolation reference)
