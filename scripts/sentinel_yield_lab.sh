#!/usr/bin/env bash
# Lab oneshot: attach a proof process, last-gasp C2, confirm Yield ended it.
# Not a CI gate name. Live K8s delete is optional (SIGNALS_YIELD_K8S=1).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
WID="${1:-signals-proof-$(date +%s)}"
CTRL="${SIGNALS_ENGINE_CONTROL:-http://127.0.0.1:50552}"
C2="${SIGNALS_C2_URL:-http://127.0.0.1:50561}"

info() { echo "sentinel-yield-lab: $*"; }

info "attach workload_id=$WID"
attach=$(curl -sf -X POST "$CTRL/workloads" \
  -H 'Content-Type: application/json' \
  -d "{\"workload_id\":\"$WID\"}")
echo "$attach"
pid=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['pid'])" "$attach")
kill -0 "$pid"
info "pid=$pid alive"

info "last-gasp → C2 → Engine/Yield"
gasp=$(curl -sf -X POST "$C2/c2-protocol/last-gasp" \
  -H 'Content-Type: application/json' \
  -d "{\"workload_id\":\"$WID\",\"project\":\"signals\",\"phase\":\"preempted\",\"sentinel_id\":\"lab\"}")
echo "$gasp"

if kill -0 "$pid" 2>/dev/null; then
  info "FAIL pid=$pid still alive after Yield"
  exit 1
fi
info "ok process ended (pid=$pid)"

if [[ "${SIGNALS_YIELD_K8S:-0}" == "1" ]]; then
  info "optional: apply/delete proof pod (root.internal.compute)"
  kubectl apply -f "$ROOT/zarf/federation/manifests/sentinels/yield-proof-pod.yaml"
  kubectl -n federation-signals wait --for=condition=Ready pod/signals-yield-proof --timeout=60s || true
  kubectl -n federation-signals delete pod signals-yield-proof --wait=true || true
fi
exit 0
