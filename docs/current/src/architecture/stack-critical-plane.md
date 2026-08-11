# Signals critical plane

**Status:** Policy (enforced via preflight)  
**Date:** 2026-08-11

A Signals deployment is not “Postgres + a few daemons.” **`devenv up` / `devenv up -d`**
is the uniform entry point for a **critical plane** that spans host processes and
RKE2 platform services. Engines integrate via [signals-protocol](../components/signals-protocol.md);
they do **not** each re-host thrashing control-plane copies of these services.

## Critical plane (uniform)

| Domain | Service | Role | Lab surface |
|--------|---------|------|-------------|
| Identity | Kerberos KDC | Data-plane authn | `just bootstrap` |
| Data SoR | PostgreSQL 16 | Catalog, AGE, Ranger, Metaflow DB | `:5455` |
| Object store | **RustFS** | S3 for artifacts, Metaflow datastore | `:9010` |
| Governance | **Atlas** (+ Marquez-web validator) | Metadata + OL SoR | `:21010` / `:21011` |
| Authz | **Ranger** | Tag/resource policies | `:6080` |
| Storage / SQL | **Kudu** + **Impala** | Analytic tables | Kudu / HS2 `:21050` |
| Federation schedule | **YuniKorn** | Multi-tenant pod admission | REST NodePort `:30080` |
| Scale-to-zero / event fabric | **Knative** Serving (+ Eventing M3) | Sentinels, triggers | Serving ns |
| Workflow production | **Airflow 3** | Metaflow DAG orchestration | NodePort `:30800` |
| Flow metadata | **Metaflow** service | Platform runs for any engine | NodePort `:30180` |
| Control UI | **signals-ui** | YK ⊇ backplane | `:9889` |

These are **uniformly critical**: missing any of them is a degraded Signals
deployment, not a supported “minimal profile” for product work. Hermetic unit
tests may still mock subsystems; the **live stack** does not.

## Not critical (by design)

| Item | Why out of critical plane |
|------|---------------------------|
| Gaius / Aegir engine processes | Federated **consumers**, not platform SoR |
| Marquez DB / stock Marquez API | Rejected — Atlas OL is lineage SoR |
| Argo Workflows / Argo Events | Rejected — Airflow + Knative Eventing |
| Engine-local Metaflow Tilt | Isolation mode outside this tree |

## Enforcement

| Tool | Behavior |
|------|----------|
| `scripts/signals_stack_preflight.sh` | Host + RKE2 critical checks; optional auto-bootstrap |
| `just stack-ready` | Same preflight |
| `devenv tasks run signals:stack-ready` | Runs before **signals-ui** on `devenv up` |
| `signals:federation-ready` | YK + Knative (subset) |
| `signals:metaflow-platform` | Metaflow metadata M1 (subset) |
| `signals:airflow-platform` | Airflow 3 LocalExecutor (M2) |
| Airflow | Auto-bootstrap when `SIGNALS_STACK_AUTO_AIRFLOW=1` (default); hard-fail when `SIGNALS_STACK_REQUIRE_AIRFLOW=1` |

```bash
just stack-ready                    # default lab gates (auto Airflow)
just airflow-platform               # Airflow 3 only
SIGNALS_STACK_REQUIRE_AIRFLOW=1 just stack-ready   # hard-require Airflow
```

## Topology

```text
devenv up [-d]
  ├── host critical: KDC, PG, RustFS, Atlas, Ranger, Kudu, Impala, signals-ui, …
  └── RKE2 critical: YuniKorn, Knative, Metaflow service, Airflow 3
            │
            ▼
     Federated engines (signals-protocol) — optional consumers
```

## Related

- [Platform Metaflow](./metaflow-platform.md)
- [signals-federation Zarf](../infrastructure/signals-federation-zarf.md)
- [Development environment](../operations/devenv.md)
