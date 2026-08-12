#!/usr/bin/env bash
# Publish a CloudEvent to the platform Knative Broker (signals-events/default).
# Replaces Argo Events publish path for Metaflow / engines / CLI.
#
# Usage:
#   scripts/signals_events_publish.sh [ce-type] [json-data]
#   SIGNALS_EVENTS_BROKER_URL=http://... scripts/signals_events_publish.sh ...
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CE_TYPE="${1:-dev.signals.eventing.smoke}"
CE_DATA="${2:-{}}"
CE_SOURCE="${SIGNALS_EVENTS_SOURCE:-dev.signals.cli}"
CE_SUBJECT="${SIGNALS_EVENTS_SUBJECT:-}"
CE_DAGID="${SIGNALS_EVENTS_DAGID:-}"

pick_kubeconfig() {
  local c
  for c in "${KUBECONFIG:-}" "${HOME}/.kube/rke2.yaml" "${HOME}/.kube/config"; do
    [[ -n "$c" && -r "$c" ]] || continue
    export KUBECONFIG="$c"
    return 0
  done
  return 1
}

info() { echo "events-publish: $*"; }
die() { echo "ERROR: events-publish: $*" >&2; exit 1; }

pick_kubeconfig || true
KCFG="${KUBECONFIG:-$HOME/.kube/rke2.yaml}"

BROKER_URL="${SIGNALS_EVENTS_BROKER_URL:-}"
if [[ -z "$BROKER_URL" ]]; then
  command -v kubectl >/dev/null || die "kubectl required to resolve broker URL"
  BROKER_URL=$(kubectl --kubeconfig "$KCFG" \
    -n signals-events get broker default -o jsonpath='{.status.address.url}' 2>/dev/null || true)
fi
[[ -n "$BROKER_URL" ]] || die "Broker URL empty — run just knative-eventing"

CE_ID="ce-$(date -u +%Y%m%dT%H%M%SZ)-$$"
info "type=$CE_TYPE source=$CE_SOURCE broker=$BROKER_URL id=$CE_ID"

# Publish from in-cluster (python already running in sink — avoids curl image Zarf rewrite).
# Fallback: Job with python:3.12-slim + zarf ignore.
if kubectl --kubeconfig "$KCFG" -n signals-events get deploy airflow-dag-trigger &>/dev/null; then
  info "publishing via airflow-dag-trigger pod"
  kubectl --kubeconfig "$KCFG" -n signals-events exec deploy/airflow-dag-trigger -- \
    python3 -c "
import json, urllib.request, os, sys
url = os.environ.get('BROKER', '''$BROKER_URL''')
body = '''$CE_DATA'''.encode()
headers = {
  'Content-Type': 'application/json',
  'Ce-Id': '''$CE_ID''',
  'Ce-Specversion': '1.0',
  'Ce-Type': '''$CE_TYPE''',
  'Ce-Source': '''$CE_SOURCE''',
}
subj = '''$CE_SUBJECT'''
dagid = '''$CE_DAGID'''
if subj:
  headers['Ce-Subject'] = subj
if dagid:
  headers['Ce-Dagid'] = dagid
req = urllib.request.Request(url, data=body, method='POST', headers=headers)
try:
  with urllib.request.urlopen(req, timeout=90) as r:
    print(r.read().decode()[:300])
    print('HTTP', r.status)
except Exception as e:
  # Broker may block until the sink finishes Airflow JWT+dagRun (can exceed 30s).
  # Delivery often still succeeds — smoke scripts poll Airflow separately.
  print('WARN publish wait:', type(e).__name__, e, file=sys.stderr)
  print('HTTP 000 (client timeout; event may still be delivered)')
"
else
  die "airflow-dag-trigger deploy missing — just knative-eventing"
fi

info "published $CE_ID — check Airflow DAG runs (signals_eventing_smoke / mapped dag)"
