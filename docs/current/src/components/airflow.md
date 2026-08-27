# Airflow

Apache Airflow **3.x** is the **production orchestrator** for platform Metaflow
DAGs on Signals RKE2 (not Argo Workflows). Lab-grade install uses the official
Helm chart from the `components/airflow` submodule (appVersion **3.1.7**).

| Concern | Choice |
|---------|--------|
| Chart | `components/airflow/chart` (1.20.0-dev / AF **3.1.7**) |
| Executor | **LocalExecutor** (lab baseline; no Redis/Celery) |
| Metadata DB | Host devenv PostgreSQL (`airflow` DB, bridged into ns) |
| UI / REST | API server NodePort **30800** |
| Metaflow deploy | `python flow.py airflow create dag.py` |
| Task runtime | `KubernetesPodOperator` → RKE2 pods (RBAC → `metaflow`) |
| Scheduler of pods | **YuniKorn** (federation queues) |
| Time triggers | Metaflow `@schedule` |
| Event triggers | **Knative Eventing** → Airflow DAG runs (M3) |

Full architecture: [Platform Metaflow](../architecture/metaflow-platform.md) ·
[Critical plane](../architecture/stack-critical-plane.md).

## Status

| Phase | State |
|-------|--------|
| Component submodule | `components/airflow` |
| Platform deploy on RKE2 | **M2** — `just airflow-platform` |
| CI DAG | `signals_ci` (ConfigMap) · `just airflow-platform-ci` |
| Knative Eventing → DAG trigger | **M3** — `just knative-eventing` / `just airflow-eventing-ci` |

## Lab operations

```bash
# Deploy / upgrade (idempotent)
just airflow-platform

# Status
just airflow-platform-status

# UI URL + component health (OPEN=1 opens a browser)
just airflow-ui

# Trigger CI DAG and wait for success
just airflow-platform-ci

# Critical plane preflight (auto-bootstraps Airflow when SIGNALS_STACK_AUTO_AIRFLOW=1)
just stack-ready
just signals-ready                  # check-only oneshot
SIGNALS_STACK_REQUIRE_AIRFLOW=1 just stack-ready
```

| Surface | Value |
|---------|--------|
| UI / API | `http://127.0.0.1:30800` (NodePort **30800**) |
| Admin | `admin` / `admin` (lab only) |
| API auth | AF3 JWT: `POST /auth/token` → `Authorization: Bearer …` for `/api/v2` |
| Namespace | `airflow` |
| Secrets file | `build/config/airflow-secrets.env` (gitignored; fernet/jwt/api) |
| Values | `config/k8s/airflow/values-signals.yaml` |
| Host PG bridge | `signals-postgres-proxy` (hostNetwork socat → `127.0.0.1:5455`) |
| Zarf | `zarf.dev/agent: ignore` until packaged into federation |

## UI

The Airflow 3 UI is the API server itself (React SPA + `/api/v2`) on NodePort
**30800** — the RKE2 analogue of Marquez-web on `:21011`; both are listed in the
`devenv` shell summary. `just airflow-ui` prints the URL and the
`/api/v2/monitor/health` component status.

**Direction — top-down schedule view.** Airflow is where every federated
engine's schedule should be visible in one place: Metaflow flows deploy as DAGs
(`python flow.py airflow create`), and pg_cron clocks on peer engines (e.g. Gaius
`gpu-metrics-settle`) are to be mirrored here as DAGs. Until an image carries the
`signals.*` package, `config/k8s/airflow/dags/gpu_metrics_settle_dag.py` is **not**
mounted (its `signals.ops` import would surface as a DAG import error).

**Stability note.** `scripts/signals_stack_preflight.sh` lets an installed Broker
settle (`SIGNALS_STACK_EVENTING_WAIT`, default 120s) before re-running the Eventing
bootstrap, and the bootstrap only replaces Zarf-rewritten pods and only restarts the
dag-processor when the DAG ConfigMap changed — re-bootstrapping on every
signals-ui restart used to roll the eventing control plane and the dag-processor
each iteration.

## Related

- Outerbounds [Airflow + Metaflow ops](https://docs.outerbounds.com/engineering/operations/airflow/)
- Metaflow [scheduling with Airflow](https://docs.metaflow.org/production/scheduling-metaflow-flows/scheduling-with-airflow)
