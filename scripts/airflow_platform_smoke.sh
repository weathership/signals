#!/usr/bin/env bash
# Trigger signals_smoke DAG once and wait for success (lab M2 gate).
# Airflow 3 uses JWT via POST /auth/token (not basic auth for /api/v2).
set -euo pipefail

API_URL="${AIRFLOW_API_URL:-http://127.0.0.1:30800}"
USER="${AIRFLOW_ADMIN_USER:-admin}"
PASS="${AIRFLOW_ADMIN_PASSWORD:-admin}"
DAG_ID="${AIRFLOW_SMOKE_DAG_ID:-signals_smoke}"
TIMEOUT="${AIRFLOW_SMOKE_TIMEOUT:-180}"

info() { echo "airflow-smoke: $*"; }
die() { echo "ERROR: airflow-smoke: $*" >&2; exit 1; }

info "obtaining JWT from ${API_URL}/auth/token"
TOKEN="$(curl -sS -m 15 -X POST "${API_URL}/auth/token" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"${USER}\",\"password\":\"${PASS}\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])' 2>/dev/null || true)"
[[ -n "$TOKEN" ]] || die "auth failed for user ${USER} at ${API_URL}/auth/token"

auth=(-H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json')
api_base="${API_URL}/api/v2"

# Unpause
curl -sf -m 15 "${auth[@]}" -X PATCH \
  -d '{"is_paused": false}' \
  "${api_base}/dags/${DAG_ID}" >/dev/null \
  || info "WARN: unpause returned non-2xx (may already be active)"

run_id="manual__smoke__$(date -u +%Y%m%dT%H%M%SZ)"
# Airflow 3 API requires logical_date (ISO-8601)
body="$(python3 - <<PY
import json
from datetime import datetime, timezone
print(json.dumps({
  "dag_run_id": "${run_id}",
  "logical_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
  "conf": {"source": "signals_airflow_platform_smoke"},
}))
PY
)"

info "triggering dag_run_id=$run_id"
resp="$(curl -sS -m 30 "${auth[@]}" -X POST \
  -d "$body" \
  "${api_base}/dags/${DAG_ID}/dagRuns" || true)"
echo "$resp" | head -c 500
echo

deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
  state_json="$(curl -sS -m 10 "${auth[@]}" \
    "${api_base}/dags/${DAG_ID}/dagRuns/${run_id}" 2>/dev/null || true)"
  state="$(echo "$state_json" | python3 -c 'import sys,json
try:
  print(json.load(sys.stdin).get("state",""))
except Exception:
  print("")' 2>/dev/null || true)"
  info "state=$state"
  case "$state" in
    success) info "OK — $DAG_ID $run_id success"; exit 0 ;;
    failed|upstream_failed) die "DAG run failed: $state_json" ;;
  esac
  sleep 5
done

die "timeout waiting for $DAG_ID run $run_id (last state=${state:-unknown})"
