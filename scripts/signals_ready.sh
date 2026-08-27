#!/usr/bin/env bash
# signals-ready — foundation readiness oneshot for peers + systemd.
#
# Inspired by Gaius /health (PASS | WARN | FAIL | SKIP) but **check-only**:
# no auto-bootstrap, no remediations. Exit 0 iff every *critical* check PASSes.
#
# Critical set (all required for peer dependence / signals.target ready):
#   postgres, kdc, rustfs, atlas, kudu-master, kudu-tserver,
#   impala-* (Linux), yunikorn, metaflow, airflow, knative-eventing broker
# Soft (WARN only by default): marquez-web, ranger, polaris, signals-ui, knative-serving
#
# Usage:
#   just signals-ready
#   scripts/signals_ready.sh
#   scripts/signals_ready.sh --json
#   SIGNALS_READY_STRICT_UI=1 scripts/signals_ready.sh   # fail if signals-ui down
#
# Distinct from `just stack-ready` (preflight + optional auto-bootstrap).
# See: docs/current/src/architecture/stack-critical-plane.md
#      Gaius: docs/current/src/operations/health-checks.md (PASS/WARN/FAIL pattern)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=signals_python.sh
. "$ROOT/scripts/signals_python.sh"
cd "$ROOT"

FORMAT=text
for arg in "$@"; do
  case "$arg" in
    --json) FORMAT=json ;;
    -h|--help)
      sed -n '2,22p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
  esac
done

PGHOST="${SIGNALS_PG_HOST:-127.0.0.1}"
[[ "$PGHOST" == /* ]] && PGHOST="127.0.0.1"
PGPORT="${SIGNALS_PG_PORT:-${PGPORT:-5455}}"
ATLAS_URL="${SIGNALS_ATLAS_HTTP_URL:-http://127.0.0.1:${SIGNALS_ATLAS_HTTP_PORT:-21010}}"
MARQUEZ_URL="${MARQUEZ_WEB_URL:-http://127.0.0.1:${MARQUEZ_WEB_PORT:-21011}}"
RUSTFS_URL="${RUSTFS_ADDRESS:-127.0.0.1:9010}"
YK_URL="${SIGNALS_YK_API_URL:-http://127.0.0.1:30080}"
MF_URL="${METAFLOW_SERVICE_URL:-http://127.0.0.1:30180}"
AF_URL="${AIRFLOW_API_URL:-http://127.0.0.1:30800}"
UI_URL="${SIGNALS_UI_URL:-http://127.0.0.1:9889}"

# Prefer a readable kubeconfig (lab env often sets KUBECONFIG to root-only rke2 path).
pick_kubeconfig() {
  local c
  for c in "${KUBECONFIG:-}" "${HOME}/.kube/rke2.yaml" "${HOME}/.kube/config"; do
    [[ -n "$c" && -r "$c" ]] || continue
    export KUBECONFIG="$c"
    return 0
  done
  return 1
}
KUBE_OK=0
if pick_kubeconfig; then
  KUBE_OK=1
fi

STRICT_UI="${SIGNALS_READY_STRICT_UI:-0}"
STRICT_RANGER="${SIGNALS_READY_STRICT_RANGER:-0}"
STRICT_MARQUEZ="${SIGNALS_READY_STRICT_MARQUEZ:-0}"
STRICT_SERVING="${SIGNALS_READY_STRICT_SERVING:-0}"

# results as lines: name|status|critical|message
RESULTS=()
FAILS=0
WARNS=0

tcp_ok() {
  timeout 2 bash -c "echo >/dev/tcp/${1}/${2}" 2>/dev/null
}

http_ok() {
  curl -sf -m 3 "$1" >/dev/null 2>&1
}

record() {
  local name="$1" status="$2" critical="$3" message="$4"
  RESULTS+=("${name}|${status}|${critical}|${message}")
  case "$status" in
    FAIL) FAILS=$((FAILS + 1)) ;;
    WARN) WARNS=$((WARNS + 1)) ;;
  esac
}

check_tcp() {
  local name="$1" host="$2" port="$3" critical="$4"
  if tcp_ok "$host" "$port"; then
    record "$name" PASS "$critical" "${host}:${port}"
  else
    if [[ "$critical" == "1" ]]; then
      record "$name" FAIL "$critical" "not accepting TCP ${host}:${port}"
    else
      record "$name" WARN "$critical" "not accepting TCP ${host}:${port}"
    fi
  fi
}

check_http() {
  local name="$1" url="$2" critical="$3"
  if http_ok "$url"; then
    record "$name" PASS "$critical" "$url"
  else
    if [[ "$critical" == "1" ]]; then
      record "$name" FAIL "$critical" "HTTP not OK: $url"
    else
      record "$name" WARN "$critical" "HTTP not OK: $url"
    fi
  fi
}

# ── Host critical ─────────────────────────────────────────────────
check_tcp "postgres" "$PGHOST" "$PGPORT" 1
if ss -uln 2>/dev/null | grep -qE ':8848\s'; then
  record "kdc" PASS 1 "UDP :8848"
else
  record "kdc" FAIL 1 "KDC not listening on :8848"
fi

RUSTFS_HOST="${RUSTFS_URL%%:*}"
RUSTFS_PORT="${RUSTFS_URL##*:}"
check_tcp "rustfs" "$RUSTFS_HOST" "$RUSTFS_PORT" 1

if curl -sf -m 3 http://127.0.0.1:8182/q/health/ready >/dev/null 2>&1 \
  || tcp_ok 127.0.0.1 8181; then
  record "polaris" PASS 0 "Iceberg REST :8181 (admin JDBC on pglite; data on RustFS)"
else
  record "polaris" WARN 0 "not ready on :8181/:8182 (warehouse catalog)"
fi

check_http "atlas" "${ATLAS_URL%/}/api/atlas/admin/status" 1

# ── Data plane: Kudu + Impala (always critical on Linux) ──────────
check_http "kudu-master" "http://127.0.0.1:8051/" 1
check_http "kudu-tserver" "http://127.0.0.1:8050/" 1

if [[ "$(uname -s)" == "Linux" ]]; then
  check_http "impala-statestore" "http://127.0.0.1:25010/" 1
  check_http "impala-catalogd" "http://127.0.0.1:25020/" 1
  check_http "impala-impalad-web" "http://127.0.0.1:25000/" 1
  check_tcp "impala-hs2" "127.0.0.1" "21050" 1
  # Warehouse read path: Postgres impala_fdw → Kudu (engine writes this table).
  if PGPASSWORD="${PGPASSWORD:-signals}" psql -h "$PGHOST" -p "$PGPORT" \
      -U "${PGUSER:-signals}" -d signals -Atqc \
      "SELECT 1 FROM signal_tier0 LIMIT 1" >/dev/null 2>&1; then
    record "impala_fdw" PASS 1 "SELECT signal_tier0 :${PGPORT}"
  else
    record "impala_fdw" FAIL 1 "signal_tier0 not readable via impala_fdw on :${PGPORT}"
  fi
else
  record "impala" SKIP 0 "Darwin: Impala processes not in stack"
fi

# ── Soft host services ────────────────────────────────────────────
crit_m=0; [[ "$STRICT_MARQUEZ" == "1" ]] && crit_m=1
if http_ok "${MARQUEZ_URL%/}/healthcheck" || http_ok "${MARQUEZ_URL%/}/"; then
  record "marquez-web" PASS "$crit_m" "$MARQUEZ_URL"
else
  record "marquez-web" "$([[ $crit_m -eq 1 ]] && echo FAIL || echo WARN)" "$crit_m" "not ready"
fi

crit_r=0; [[ "$STRICT_RANGER" == "1" ]] && crit_r=1
if tcp_ok 127.0.0.1 6080; then
  record "ranger-admin" PASS "$crit_r" ":6080"
else
  record "ranger-admin" "$([[ $crit_r -eq 1 ]] && echo FAIL || echo WARN)" "$crit_r" "not ready"
fi

# ── RKE2 / platform critical ──────────────────────────────────────
if http_ok "${YK_URL%/}/ws/v1/clusters"; then
  record "yunikorn" PASS 1 "$YK_URL"
else
  record "yunikorn" FAIL 1 "YK REST missing at $YK_URL"
fi

# Platform engine — WARN here: unit starts After=signals-ready, so this
# oneshot must not require :50551. lattice-ci + UI /readyz gate Status.
ENGINE_TARGET="${SIGNALS_ENGINE_TARGET:-127.0.0.1:50551}"
if signals_py "$ROOT/scripts/zndx_engine_status.py" \
    --expect-project signals --expect-capability scheduler \
    "$ENGINE_TARGET" >/dev/null 2>&1; then
  record "signals-engine" PASS 0 "$ENGINE_TARGET Engine/Status"
else
  record "signals-engine" WARN 0 "Engine/Status not up at $ENGINE_TARGET (starts after ready)"
fi

# C2 — WARN: starts After=signals-engine, so ready must not require :50561.
C2_URL="${SIGNALS_C2_URL:-http://127.0.0.1:50561}"
if http_ok "${C2_URL%/}/healthz"; then
  record "signals-c2" PASS 0 "$C2_URL/healthz"
else
  record "signals-c2" WARN 0 "C2 not up at $C2_URL (starts after engine)"
fi

# Metaflow — critical for peer Metaflow platform dependence
if http_ok "${MF_URL%/}/ping"; then
  record "metaflow" PASS 1 "${MF_URL}/ping"
else
  record "metaflow" FAIL 1 "metadata service not ready at ${MF_URL}/ping"
fi

# Airflow — critical for production DAG / event path
if http_ok "${AF_URL%/}/api/v2/version" \
  || { c=$(curl -s -o /dev/null -w '%{http_code}' -m 3 "${AF_URL%/}/" 2>/dev/null || echo 000); [[ "$c" =~ ^(200|302|303|401|403)$ ]]; }; then
  record "airflow" PASS 1 "$AF_URL"
else
  record "airflow" FAIL 1 "API not ready at $AF_URL"
fi

# Knative Eventing Broker — critical (M3 default event fabric)
if command -v kubectl >/dev/null 2>&1 && [[ "$KUBE_OK" == "1" ]]; then
  br=$(kubectl --kubeconfig "$KUBECONFIG" -n signals-events \
    get broker default -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)
  if [[ "$br" == "True" ]]; then
    url=$(kubectl --kubeconfig "$KUBECONFIG" -n signals-events \
      get broker default -o jsonpath='{.status.address.url}' 2>/dev/null || true)
    record "knative-eventing" PASS 1 "Broker Ready ${url}"
  else
    record "knative-eventing" FAIL 1 "signals-events/default Broker not Ready (kubeconfig=$KUBECONFIG)"
  fi
  # Knative Serving (soft unless STRICT)
  crit_s=0; [[ "$STRICT_SERVING" == "1" ]] && crit_s=1
  if kubectl --kubeconfig "$KUBECONFIG" -n knative-serving get deploy controller &>/dev/null; then
    av=$(kubectl --kubeconfig "$KUBECONFIG" -n knative-serving \
      get deploy controller -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo 0)
    if [[ "${av:-0}" -ge 1 ]]; then
      record "knative-serving" PASS "$crit_s" "controller available"
    else
      record "knative-serving" "$([[ $crit_s -eq 1 ]] && echo FAIL || echo WARN)" "$crit_s" "controller not available"
    fi
  else
    record "knative-serving" "$([[ $crit_s -eq 1 ]] && echo FAIL || echo WARN)" "$crit_s" "ns/deploy missing"
  fi
else
  record "knative-eventing" FAIL 1 "kubectl missing or no readable kubeconfig (tried env, ~/.kube/rke2.yaml, ~/.kube/config)"
  record "knative-serving" SKIP 0 "kubectl/kubeconfig unavailable"
fi

# signals-ui (soft by default — peers wait on foundation services first)
crit_u=0; [[ "$STRICT_UI" == "1" ]] && crit_u=1
if http_ok "${UI_URL%/}/readyz"; then
  record "signals-ui" PASS "$crit_u" "${UI_URL}/readyz"
else
  record "signals-ui" "$([[ $crit_u -eq 1 ]] && echo FAIL || echo WARN)" "$crit_u" "readyz not OK"
fi

# ── Output ────────────────────────────────────────────────────────
export SIGNALS_READY_RESULTS
SIGNALS_READY_RESULTS="$(printf '%s\n' "${RESULTS[@]}")"

if [[ "$FORMAT" == "json" ]]; then
  SIGNALS_READY_RESULTS="$SIGNALS_READY_RESULTS" python3 - <<'PY'
import json, os
raw = os.environ.get("SIGNALS_READY_RESULTS", "")
checks = []
for line in raw.split("\n"):
    if not line.strip():
        continue
    parts = line.split("|", 3)
    if len(parts) < 4:
        continue
    name, status, critical, message = parts
    checks.append({
        "name": name,
        "status": status.lower(),
        "critical": critical == "1",
        "message": message,
    })
fails = sum(1 for c in checks if c["status"] == "fail")
warns = sum(1 for c in checks if c["status"] == "warn")
print(json.dumps({"ready": fails == 0, "fails": fails, "warns": warns, "checks": checks}, indent=2))
PY
else
  echo "signals-ready: critical plane readiness (Gaius-style PASS/WARN/FAIL)"
  printf '%-22s %-6s %s\n' "COMPONENT" "STATUS" "DETAIL"
  printf '%-22s %-6s %s\n' "---------" "------" "------"
  for line in "${RESULTS[@]}"; do
    IFS='|' read -r name status critical message <<<"$line"
    mark=""
    [[ "$critical" == "1" ]] && mark="*"
    printf '%-22s %-6s %s\n' "${name}${mark}" "$status" "$message"
  done
  echo
  echo "* = critical (must PASS for exit 0)"
  echo "summary: fails=${FAILS} warns=${WARNS}"
fi

if [[ "$FAILS" -gt 0 ]]; then
  if [[ "$FORMAT" != "json" ]]; then
    echo "signals-ready: NOT READY (${FAILS} critical failure(s))" >&2
  fi
  exit 1
fi
if [[ "$FORMAT" != "json" ]]; then
  echo "signals-ready: READY"
fi
exit 0
