#!/usr/bin/env bash
# One-off wrapper → elevated CI gate. Prefer: just airflow-platform-ci
# Kept for local/ad-hoc use under ./scripts/ (smoke naming).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "airflow-platform-smoke: delegating to airflow_platform_ci.sh (elevated gate is CI)" >&2
exec bash "$ROOT/scripts/airflow_platform_ci.sh" "$@"
