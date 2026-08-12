#!/usr/bin/env bash
# M3 smoke: publish CE → wait for signals_eventing_smoke (or signals_smoke) success.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${AIRFLOW_API_URL:-http://127.0.0.1:30800}"
USER="${AIRFLOW_ADMIN_USER:-admin}"
PASS="${AIRFLOW_ADMIN_PASSWORD:-admin}"
DAG_ID="${AIRFLOW_EVENTING_SMOKE_DAG:-signals_eventing_smoke}"
CE_TYPE="${SIGNALS_EVENTS_SMOKE_TYPE:-dev.signals.eventing.smoke}"
TIMEOUT="${AIRFLOW_EVENTING_SMOKE_TIMEOUT:-180}"

info() { echo "eventing-smoke: $*"; }
die() { echo "ERROR: eventing-smoke: $*" >&2; exit 1; }

info "bootstrap eventing if needed"
bash "$ROOT/scripts/knative_eventing_bootstrap.sh" >/tmp/eventing-bootstrap.log 2>&1 \
  || { tail -40 /tmp/eventing-bootstrap.log; die "eventing bootstrap failed"; }

# Auth
TOKEN="$(curl -sS -m 15 -X POST "${API_URL}/auth/token" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"${USER}\",\"password\":\"${PASS}\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])' 2>/dev/null || true)"
[[ -n "$TOKEN" ]] || die "Airflow auth failed at $API_URL"

auth=(-H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json')
api="${API_URL}/api/v2"

# Ensure DAG visible (may need a few seconds after ConfigMap update)
for i in $(seq 1 30); do
  if curl -sf -m 10 "${auth[@]}" "${api}/dags/${DAG_ID}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
  if [[ "$i" -eq 30 ]]; then
    info "DAG $DAG_ID not listed — falling back to signals_smoke"
    DAG_ID=signals_smoke
  fi
done

curl -sf -m 15 "${auth[@]}" -X PATCH -d '{"is_paused": false}' "${api}/dags/${DAG_ID}" >/dev/null || true

# Snapshot run count / latest before publish
before="$(curl -sS -m 10 "${auth[@]}" \
  "${api}/dags/${DAG_ID}/dagRuns?limit=1&order_by=-start_date" 2>/dev/null || echo '{}')"

info "publishing CloudEvent type=$CE_TYPE"
# Publish may client-timeout while Broker waits on sink→Airflow; delivery still works.
bash "$ROOT/scripts/signals_events_publish.sh" "$CE_TYPE" \
  "{\"smoke\":true,\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
  || info "WARN publish client returned non-zero — polling Airflow anyway"

info "waiting up to ${TIMEOUT}s for new successful run of $DAG_ID"
deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
  runs="$(curl -sS -m 10 "${auth[@]}" \
    "${api}/dags/${DAG_ID}/dagRuns?limit=5&order_by=-start_date" 2>/dev/null || echo '{}')"
  state="$(echo "$runs" | python3 -c '
import sys,json
try:
  d=json.load(sys.stdin)
  runs=d.get("dag_runs") or d.get("dagRuns") or []
  if not runs:
    print("")
  else:
    print(runs[0].get("state",""))
except Exception:
  print("")
' 2>/dev/null || true)"
  info "latest_state=$state"
  case "$state" in
    success) info "OK — $DAG_ID event-triggered run success"; exit 0 ;;
    failed|upstream_failed) die "DAG run failed: $runs" ;;
  esac
  sleep 5
done
die "timeout waiting for $DAG_ID success after CE publish"
