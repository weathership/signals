# Airflow 3 M2 platform land (2026-08-11)

## What shipped

| Item | Path / surface |
|------|----------------|
| Chart | `components/airflow/chart` appVersion **3.1.7** |
| Values | `config/k8s/airflow/values-signals.yaml` |
| Host PG proxy | `config/k8s/airflow/host-bridge.yaml` (hostNetwork socat) |
| Cross-ns RBAC | `config/k8s/airflow/rbac-metaflow.yaml` |
| Smoke DAG | `config/k8s/airflow/dags/signals_smoke_dag.py` |
| Bootstrap | `scripts/airflow_platform_bootstrap.sh` · `just airflow-platform` |
| Smoke | `scripts/airflow_platform_smoke.sh` · `just airflow-platform-smoke` |
| Stack preflight | auto-bootstrap when `SIGNALS_STACK_AUTO_AIRFLOW=1` |
| Lab URL | `http://127.0.0.1:30800` NodePort **30800** |

## Shape

- **LocalExecutor** (no Redis/Celery)
- External PG DB `airflow` / user `airflow` on devenv `:5455`
- API server + scheduler + dag-processor + triggerer
- `workers.persistence.enabled=false` → Deployments + emptyDir (no default SC)
- `zarf.dev/agent: ignore` so images pull `apache/airflow:3.1.7` not Zarf rewrite

## Lab fixes during bring-up

1. **Zarf rewrite** — same as Metaflow; annotate pods/ns `zarf.dev/agent: ignore`
2. **PVC Pending** — LocalExecutor + default `workers.persistence.enabled` created StatefulSet log PVCs with no StorageClass → disable worker/triggerer persistence
3. **PG loopback** — Endpoints→node IP cannot reach `listen_addresses=127.0.0.1` → hostNetwork socat proxy `15432→127.0.0.1:5455`
4. **ConfigMap DAG dir recursion** — mount single file via `subPath`, not whole CM dir
5. **AF3 API** — JWT via `POST /auth/token`; dagRuns require `logical_date`

## Verified

```text
curl http://127.0.0.1:30800/api/v2/version  → 3.1.7
just airflow-platform-smoke                 → signals_smoke success
```

## Next

- M3 Knative Eventing → DAG-run sink
- Optional: open devenv PG listen for pod CIDR (retire socat)
- Package Airflow image into signals-federation Zarf (drop zarf ignore)
