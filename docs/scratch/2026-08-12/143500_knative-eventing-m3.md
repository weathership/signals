# Knative Eventing M3 land (2026-08-12)

## Delivered

- Knative Eventing **v1.23.0** (aligned with Serving) + IMC + MT channel broker
- Namespace `signals-events`, Broker `default` Ready
- Sink `airflow-dag-trigger`: CE → AF3 JWT → `POST /api/v2/dags/{id}/dagRuns`
- Triggers for smoke / metaflow.finished / gaius.curate / signals.smoke
- DAG `signals_eventing_smoke` + ConfigMap dual-file mount
- `just knative-eventing` · `just events-publish` · `just airflow-eventing-smoke`

## Verified

```text
CE type=dev.signals.eventing.smoke
  → Broker signals-events/default
  → Trigger airflow-eventing-smoke
  → sink 202
  → Airflow dag_run state=success (signals_eventing_smoke)
```

## Notes

- Zarf agent rewrites Eventing images unless pod `zarf.dev/agent: ignore` (bootstrap patches deploys).
- Broker ingress can client-timeout while waiting on sink→Airflow latency; delivery still succeeds (smoke polls Airflow).
- Package Eventing images into signals-federation Zarf in a follow-up for air-gap.
