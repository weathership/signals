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
| Scale-to-zero / event fabric | **Knative** Serving + **Eventing** | Sentinels + CE→Airflow | Serving + `signals-events` Broker |
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
| `devenv up -d` | Turn-key entry: full process graph + stack-ready before signals-ui |
| `scripts/signals_stack_preflight.sh` | Host (PG/RustFS/Atlas/**Kudu/Impala**) + RKE2; auto Metaflow/Airflow |
| `scripts/signals_ready.sh` | **Check-only** Gaius-style PASS/WARN/FAIL oneshot (peers / systemd) |
| `scripts/data_plane_preflight.sh` | Binary gate before Kudu/Impala (no compile) |
| `scripts/devenv_process_assert.sh` | Fail if process graph is a partial `up` |
| `just stack-ready` | Preflight + optional auto-bootstrap (also automatic on `up -d`) |
| `just signals-ready` | Check-only readiness; critical includes **Kudu + Metaflow** |
| `signals:kerberos-bootstrap` | Wait for KDC → keytabs + kinit before Kudu/Impala |
| `signals:federation-ready` | YK + Knative (subset) |
| `signals:metaflow-platform` / `airflow-platform` | Platform RKE2 services |

```bash
devenv up -d                        # preferred — full validate + bootstrap
just stack-ready                    # preflight (may bootstrap missing pieces)
just signals-ready                  # check-only oneshot for peers / systemd
just data-plane-ci                  # Kudu/Impala ports after up (elevated CI gate)
```

### Naming: ready vs CI vs smoke

| Surface | Role |
|---------|------|
| **signals-ready** | Foundation readiness (PASS/WARN/FAIL). Exit 0 iff critical set is ready. |
| **\*-ci** | Elevated continuous-integration gates (`just airflow-platform-ci`, DAG ids `signals_ci`, CE `dev.signals.eventing.ci`) |
| **smoke** | One-off scripts under `./scripts/` (and some `./tests/`); thin wrappers may still exist for habit |

Do **not** elevate “smoke” into system recipe / package / CloudEvent API names — that role is **CI**.

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
