#!/usr/bin/env bash
# Signals critical-plane preflight for `devenv up [-d]` / just stack-ready.
#
# Uniformly critical: Kerberos/PG/RustFS (host), YK+Knative (RKE2), Metaflow
# metadata (RKE2), and (when enabled) Airflow. See:
#   docs/current/src/architecture/stack-critical-plane.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AUTO_FEDERATION="${SIGNALS_STACK_AUTO_FEDERATION:-1}"
AUTO_METAFLOW="${SIGNALS_STACK_AUTO_METAFLOW:-1}"
AUTO_AIRFLOW="${SIGNALS_STACK_AUTO_AIRFLOW:-1}"
REQUIRE_AIRFLOW="${SIGNALS_STACK_REQUIRE_AIRFLOW:-0}"
YK_URL="${SIGNALS_YK_API_URL:-http://127.0.0.1:30080}"
MF_URL="${METAFLOW_SERVICE_URL:-http://127.0.0.1:30180}"
AF_URL="${AIRFLOW_API_URL:-http://127.0.0.1:30800}"
RUSTFS_URL="${RUSTFS_ADDRESS:-127.0.0.1:9010}"
# devenv may set PGHOST to a unix socket dir — use TCP for critical-plane probe
PGHOST="${SIGNALS_PG_HOST:-127.0.0.1}"
if [[ "$PGHOST" == /* ]]; then
  PGHOST="127.0.0.1"
fi
PGPORT="${PGPORT:-5455}"
ATLAS_URL="${SIGNALS_ATLAS_HTTP_URL:-http://127.0.0.1:${SIGNALS_ATLAS_HTTP_PORT:-21010}}"

info() { echo "stack-preflight: $*"; }
die() { echo "ERROR: stack-preflight: $*" >&2; exit 1; }
ok() { info "OK  $*"; }
fail_soft() { info "WARN $*"; WARNINGS=$((WARNINGS + 1)); }

WARNINGS=0

tcp_ok() {
  local host="$1" port="$2"
  # bash /dev/tcp if available
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

if http_ok "${ATLAS_URL%/}/api/atlas/admin/version" || http_ok "${ATLAS_URL%/}/"; then
  ok "Atlas ${ATLAS_URL}"
else
  fail_soft "Atlas not ready at ${ATLAS_URL} (start devenv atlas process)"
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

# ── RKE2: Airflow 3 (platform production orchestrator) ────────────
info "=== Airflow (platform production orchestrator) ==="
pick_kube() {
  local c
  for c in "${KUBECONFIG:-}" "${HOME}/.kube/rke2.yaml" "${HOME}/.kube/config"; do
    [[ -n "$c" && -r "$c" ]] || continue
    export KUBECONFIG="$c"
    return 0
  done
  return 1
}
pick_kube || true

airflow_http_ok() {
  # AF3 public version endpoint, or UI root accepting
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
      fail_soft "Airflow bootstrap failed — run: just airflow-platform"
    fi
  else
    if [[ "$REQUIRE_AIRFLOW" == "1" || "$REQUIRE_AIRFLOW" == "true" ]]; then
      die "Airflow not deployed (critical). Run: just airflow-platform"
    fi
    fail_soft "Airflow not up at ${AF_URL} (SIGNALS_STACK_AUTO_AIRFLOW=0) — just airflow-platform"
  fi
fi

# ── Summary ───────────────────────────────────────────────────────
info "=== summary ==="
if [[ "$WARNINGS" -gt 0 ]]; then
  info "completed with ${WARNINGS} warning(s) — critical plane partially degraded"
  info "full policy: docs/current/src/architecture/stack-critical-plane.md"
  # Soft warnings only (Atlas warm-up, Airflow M2): still exit 0 so devenv up proceeds
  exit 0
fi
info "critical plane OK (host data plane + YK + Knative + Metaflow + Airflow)"
info "  YK=$YK_URL  Metaflow=$MF_URL  Airflow=$AF_URL  RustFS=$RUSTFS_URL  PG=${PGHOST}:${PGPORT}"
