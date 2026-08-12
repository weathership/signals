#!/usr/bin/env bash
# One-off wrapper → elevated CI gate. Prefer: just airflow-eventing-ci
# Kept for local/ad-hoc use under ./scripts/ (smoke naming).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "airflow-eventing-smoke: delegating to airflow_eventing_ci.sh (elevated gate is CI)" >&2
exec bash "$ROOT/scripts/airflow_eventing_ci.sh" "$@"
