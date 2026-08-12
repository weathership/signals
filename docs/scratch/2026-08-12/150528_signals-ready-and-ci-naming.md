# signals-ready + smoke→ci naming

**Date:** 2026-08-12

## Intent

1. **signals-ready** — Gaius-style PASS/WARN/FAIL oneshot for peers and systemd.
   Check-only (no auto-bootstrap). Critical set includes **Kudu** and **Metaflow**.
2. Elevated system gates use **CI** naming (`*.ci.*`, `just *-ci`), not smoke.
3. Keep **smoke** for one-off `./scripts/` (and some tests); thin wrappers may remain.

## Surfaces

| Surface | Purpose |
|---------|---------|
| `just signals-ready` / `scripts/signals_ready.sh` | Check-only readiness |
| `just stack-ready` | Preflight + optional auto-bootstrap (unchanged role) |
| `just data-plane-ci` / `airflow-platform-ci` / `airflow-eventing-ci` | Elevated CI gates |
| `signals_ci` / `signals_eventing_ci` DAGs | Platform CI DAG ids |
| `dev.signals.eventing.ci` / `dev.signals.ci.trigger` | Primary CE types |
| Legacy `*.smoke.*` CE/DAG/just aliases | Dual-mapped during transition |

## Gaius alignment

Gaius `health/checker.py`: PASS | WARN | FAIL | SKIP, critical flag, JSON.
signals-ready mirrors status vocabulary and critical/soft split without remediation.
Peers should wait on `signals-ready` exit 0, not reimplement port probes.

## Critical checks (signals-ready)

postgres, kdc, rustfs, atlas, kudu-master, kudu-tserver, impala-* (Linux),
yunikorn, metaflow, airflow, knative-eventing broker.

Soft by default: marquez-web, ranger, signals-ui, knative-serving.
