#!/usr/bin/env bash
# Signals critical-plane preflight for `devenv up [-d]` / just stack-ready.
#
# Host: PG, RustFS, Atlas, Kudu, Impala (+ process graph assert)
# RKE2: YK + Knative, Metaflow, Airflow
# See: docs/current/src/architecture/stack-critical-plane.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AUTO_FEDERATION="${SIGNALS_STACK_AUTO_FEDERATION:-1}"
AUTO_METAFLOW="${SIGNALS_STACK_AUTO_METAFLOW:-1}"
AUTO_AIRFLOW="${SIGNALS_STACK_AUTO_AIRFLOW:-1}"
AUTO_EVENTING="${SIGNALS_STACK_AUTO_EVENTING:-1}"
# Lab default: Airflow is critical once M2 landed
REQUIRE_AIRFLOW="${SIGNALS_STACK_REQUIRE_AIRFLOW:-1}"
REQUIRE_EVENTING="${SIGNALS_STACK_REQUIRE_EVENTING:-1}"
REQUIRE_DATA_PLANE="${SIGNALS_STACK_REQUIRE_DATA_PLANE:-1}"
DATA_PLANE_SMOKE="${SIGNALS_STACK_DATA_PLANE_SMOKE:-1}"
AUTO_CATALOG="${SIGNALS_STACK_AUTO_CATALOG:-1}"
ASSERT_PROCESSES="${SIGNALS_STACK_ASSERT_PROCESSES:-1}"

YK_URL="${SIGNALS_YK_API_URL:-http://127.0.0.1:30080}"
MF_URL="${METAFLOW_SERVICE_URL:-http://127.0.0.1:30180}"
AF_URL="${AIRFLOW_API_URL:-http://127.0.0.1:30800}"
RUSTFS_URL="${RUSTFS_ADDRESS:-127.0.0.1:9010}"
PGHOST="${SIGNALS_PG_HOST:-127.0.0.1}"
if [[ "$PGHOST" == /* ]]; then
  PGHOST="127.0.0.1"
fi
# Lab lattice: signals owns 5455 (see scripts/signals_port_lattice.sh)
PGPORT="${SIGNALS_PG_PORT:-${PGPORT:-5455}}"
ATLAS_URL="${SIGNALS_ATLAS_HTTP_URL:-http://127.0.0.1:${SIGNALS_ATLAS_HTTP_PORT:-21010}}"

info() { echo "stack-preflight: $*"; }
die() { echo "ERROR: stack-preflight: $*" >&2; exit 1; }
ok() { info "OK  $*"; }
fail_soft() { info "WARN $*"; WARNINGS=$((WARNINGS + 1)); }

WARNINGS=0

tcp_ok() {
  local host="$1" port="$2"
  timeout 2 bash -c "echo >/dev/tcp/${host}/${port}" 2>/dev/null
}

http_ok() {
  curl -sf -m 3 "$1" >/dev/null 2>&1
}

# ── Host critical ─────────────────────────────────────────────────
info "=== host critical plane ==="

if tcp_ok "${PGHOST}" "${PGPORT}"; then
  ok "PostgreSQL ${PGHOST}:${PGPORT}"
else
  die "PostgreSQL not reachable at ${PGHOST}:${PGPORT} (devenv postgres)"
fi

RUSTFS_HOST="${RUSTFS_URL%%:*}"
RUSTFS_PORT="${RUSTFS_URL##*:}"
if tcp_ok "${RUSTFS_HOST}" "${RUSTFS_PORT}"; then
  ok "RustFS ${RUSTFS_URL}"
else
  die "RustFS not reachable at ${RUSTFS_URL} (devenv rustfs — object plane is critical)"
fi

if http_ok "${ATLAS_URL%/}/api/atlas/admin/status" \
  || http_ok "${ATLAS_URL%/}/api/atlas/admin/version" \
  || http_ok "${ATLAS_URL%/}/"; then
  ok "Atlas ${ATLAS_URL}"
else
  if [[ "$REQUIRE_DATA_PLANE" == "1" ]]; then
    die "Atlas not ready at ${ATLAS_URL}"
  fi
  fail_soft "Atlas not ready at ${ATLAS_URL}"
fi

# ── Data plane: Kudu + Impala (wait — may race with parallel process start) ─
info "=== data plane (Kudu + Impala) ==="
DATA_PLANE_WAIT="${SIGNALS_STACK_DATA_PLANE_WAIT:-180}"
wait_http() {
  local url="$1" label="$2" secs="${3:-$DATA_PLANE_WAIT}"
  local i
  for i in $(seq 1 "$secs"); do
    if http_ok "$url"; then
      ok "$label"
      return 0
    fi
    sleep 1
  done
  return 1
}
wait_tcp() {
  local host="$1" port="$2" label="$3" secs="${4:-$DATA_PLANE_WAIT}"
  local i
  for i in $(seq 1 "$secs"); do
    if tcp_ok "$host" "$port"; then
      ok "$label"
      return 0
    fi
    sleep 1
  done
  return 1
}

data_plane_ok=1
if ! wait_http "http://127.0.0.1:8051/" "Kudu master web :8051" "$DATA_PLANE_WAIT"; then
  data_plane_ok=0
  if [[ "$REQUIRE_DATA_PLANE" == "1" ]]; then
    die "Kudu master not up on :8051 after ${DATA_PLANE_WAIT}s (devenv up -d full graph?)"
  fi
  fail_soft "Kudu master :8051 not ready"
fi
if ! wait_http "http://127.0.0.1:8050/" "Kudu tserver web :8050" 60; then
  data_plane_ok=0
  if [[ "$REQUIRE_DATA_PLANE" == "1" ]]; then
    die "Kudu tserver not up on :8050"
  fi
  fail_soft "Kudu tserver :8050 not ready"
fi

if [[ "$(uname -s)" == "Linux" ]]; then
  for pair in "25010:statestore" "25020:catalogd" "25000:impalad-web"; do
    port="${pair%%:*}"; name="${pair##*:}"
    if ! wait_http "http://127.0.0.1:${port}/" "Impala ${name} :${port}" 120; then
      data_plane_ok=0
      if [[ "$REQUIRE_DATA_PLANE" == "1" ]]; then
        die "Impala ${name} not up on :${port}"
      fi
      fail_soft "Impala ${name} :${port} not ready"
    fi
  done
  if ! wait_tcp 127.0.0.1 21050 "Impala HS2 :21050" 60; then
    data_plane_ok=0
    if [[ "$REQUIRE_DATA_PLANE" == "1" ]]; then
      die "Impala HS2 not accepting on :21050"
    fi
    fail_soft "Impala HS2 :21050 not ready"
  fi
else
  info "Darwin: Impala process checks skipped (Linux-only)"
fi

if [[ "$ASSERT_PROCESSES" == "1" || "$ASSERT_PROCESSES" == "true" ]]; then
  info "=== process graph assert (port probes; no nested devenv) ==="
  # Already waited on data-plane ports above — assert with short wait for remainder
  export SIGNALS_PROCESS_ASSERT_WAIT="${SIGNALS_PROCESS_ASSERT_WAIT:-30}"
  if bash "$ROOT/scripts/devenv_process_assert.sh"; then
    ok "host process graph (ports)"
  else
    if [[ "$REQUIRE_DATA_PLANE" == "1" ]]; then
      die "process graph incomplete — just stack-reset or devenv processes down && devenv up -d"
    fi
    fail_soft "process graph incomplete"
  fi
fi

# ── Catalog schema (idempotent) ───────────────────────────────────
if [[ "$AUTO_CATALOG" == "1" || "$AUTO_CATALOG" == "true" ]]; then
  if command -v psql >/dev/null 2>&1 && tcp_ok "${PGHOST}" "${PGPORT}"; then
    # Ensure signals role + catalog schema present
    if ! PGPASSWORD="${PGPASSWORD:-}" psql -h "$PGHOST" -p "$PGPORT" -U "${USER:-signals}" -d signals_catalog -c '\dt' >/dev/null 2>&1 \
      && ! PGPASSWORD="${PGPASSWORD:-signals}" psql -h "$PGHOST" -p "$PGPORT" -U signals -d signals_catalog -c '\dt' >/dev/null 2>&1; then
      info "catalog not ready — running signals:catalog-init path"
      if command -v devenv >/dev/null 2>&1; then
        devenv tasks run signals:catalog-init 2>/dev/null || {
          # Fallback inline minimal role (full schema via task preferred)
          info "WARN catalog-init task failed — try: devenv tasks run signals:catalog-init"
        }
      fi
    else
      ok "signals_catalog reachable"
    fi
  fi
fi

# ── RKE2: federation (YK + Knative) ───────────────────────────────
info "=== RKE2 federation (YuniKorn + Knative) ==="
export SIGNALS_YK_API_URL="$YK_URL"
if [[ "$AUTO_FEDERATION" == "1" || "$AUTO_FEDERATION" == "true" ]]; then
  bash "$ROOT/scripts/federation_preflight.sh" || die "federation preflight failed"
else
  if http_ok "${YK_URL%/}/ws/v1/clusters"; then
    ok "YuniKorn REST ${YK_URL}"
  else
    die "YuniKorn REST missing at ${YK_URL} (SIGNALS_STACK_AUTO_FEDERATION=0)"
  fi
fi

# ── RKE2: Metaflow platform ───────────────────────────────────────
info "=== platform Metaflow ==="
if http_ok "${MF_URL%/}/ping"; then
  ok "Metaflow metadata ${MF_URL}/ping"
else
  if [[ "$AUTO_METAFLOW" == "1" || "$AUTO_METAFLOW" == "true" ]]; then
    info "Metaflow not up — running metaflow_platform_bootstrap.sh"
    bash "$ROOT/scripts/metaflow_platform_bootstrap.sh" || die "metaflow platform bootstrap failed"
    http_ok "${MF_URL%/}/ping" || die "Metaflow still not healthy at ${MF_URL}/ping"
    ok "Metaflow metadata ${MF_URL}/ping (after bootstrap)"
  else
    die "Metaflow metadata missing at ${MF_URL}/ping (run: just metaflow-platform)"
  fi
fi

# ── RKE2: Airflow 3 ───────────────────────────────────────────────
info "=== Airflow (platform production orchestrator) ==="
airflow_http_ok() {
  http_ok "${AF_URL%/}/api/v2/version" \
    || { local c; c="$(curl -s -o /dev/null -w '%{http_code}' -m 3 "${AF_URL%/}/" 2>/dev/null || echo 000)"; [[ "$c" =~ ^(200|302|303|401|403)$ ]]; }
}

if airflow_http_ok; then
  ok "Airflow API ${AF_URL}"
else
  if [[ "$AUTO_AIRFLOW" == "1" || "$AUTO_AIRFLOW" == "true" ]]; then
    info "Airflow not up — running airflow_platform_bootstrap.sh"
    if bash "$ROOT/scripts/airflow_platform_bootstrap.sh"; then
      if airflow_http_ok; then
        ok "Airflow API ${AF_URL} (after bootstrap)"
      else
        if [[ "$REQUIRE_AIRFLOW" == "1" || "$REQUIRE_AIRFLOW" == "true" ]]; then
          die "Airflow bootstrap finished but API not healthy at ${AF_URL}"
        fi
        fail_soft "Airflow bootstrap finished but API not yet healthy at ${AF_URL}"
      fi
    else
      if [[ "$REQUIRE_AIRFLOW" == "1" || "$REQUIRE_AIRFLOW" == "true" ]]; then
        die "Airflow platform bootstrap failed"
      fi
      fail_soft "Airflow bootstrap failed — just airflow-platform"
    fi
  else
    if [[ "$REQUIRE_AIRFLOW" == "1" || "$REQUIRE_AIRFLOW" == "true" ]]; then
      die "Airflow not deployed. Run: just airflow-platform"
    fi
    fail_soft "Airflow not up at ${AF_URL}"
  fi
fi

# ── RKE2: Knative Eventing (M3 — CE → Airflow, no Argo) ───────────
info "=== Knative Eventing (platform event fabric) ==="
eventing_ok() {
  command -v kubectl >/dev/null 2>&1 || return 1
  kubectl --kubeconfig "${KUBECONFIG:-$HOME/.kube/rke2.yaml}" get ns knative-eventing &>/dev/null 2>&1 || return 1
  local r
  r=$(kubectl --kubeconfig "${KUBECONFIG:-$HOME/.kube/rke2.yaml}" -n signals-events \
    get broker default -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)
  [[ "$r" == "True" ]]
}
if eventing_ok; then
  ok "Knative Eventing Broker signals-events/default Ready"
else
  if [[ "$AUTO_EVENTING" == "1" || "$AUTO_EVENTING" == "true" ]]; then
    info "Eventing not ready — running knative_eventing_bootstrap.sh"
    if bash "$ROOT/scripts/knative_eventing_bootstrap.sh"; then
      if eventing_ok; then
        ok "Knative Eventing Broker Ready (after bootstrap)"
      else
        if [[ "$REQUIRE_EVENTING" == "1" || "$REQUIRE_EVENTING" == "true" ]]; then
          die "Eventing bootstrap finished but Broker not Ready"
        fi
        fail_soft "Eventing bootstrap finished but Broker not Ready"
      fi
    else
      if [[ "$REQUIRE_EVENTING" == "1" || "$REQUIRE_EVENTING" == "true" ]]; then
        die "Knative Eventing bootstrap failed"
      fi
      fail_soft "Eventing bootstrap failed — just knative-eventing"
    fi
  else
    if [[ "$REQUIRE_EVENTING" == "1" || "$REQUIRE_EVENTING" == "true" ]]; then
      die "Eventing not ready (SIGNALS_STACK_AUTO_EVENTING=0)"
    fi
    fail_soft "Eventing not ready — just knative-eventing"
  fi
fi

# ── Optional data-plane smoke ─────────────────────────────────────
if [[ "$data_plane_ok" -eq 1 && ( "$DATA_PLANE_SMOKE" == "1" || "$DATA_PLANE_SMOKE" == "true" ) ]]; then
  info "=== data-plane smoke ==="
  if bash "$ROOT/scripts/data_plane_smoke.sh"; then
    ok "data-plane smoke"
  else
    if [[ "$REQUIRE_DATA_PLANE" == "1" ]]; then
      die "data-plane smoke failed"
    fi
    fail_soft "data-plane smoke failed"
  fi
fi

# ── Summary ───────────────────────────────────────────────────────
info "=== summary ==="
if [[ "$WARNINGS" -gt 0 ]]; then
  info "completed with ${WARNINGS} warning(s) — critical plane partially degraded"
  info "full policy: docs/current/src/architecture/stack-critical-plane.md"
  exit 0
fi
info "critical plane OK (host + Kudu/Impala + YK + Knative + Metaflow + Airflow)"
info "  YK=$YK_URL  Metaflow=$MF_URL  Airflow=$AF_URL  RustFS=$RUSTFS_URL  PG=${PGHOST}:${PGPORT}"
