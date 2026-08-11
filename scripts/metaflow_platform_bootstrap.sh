#!/usr/bin/env bash
# M1: Platform Metaflow metadata service on local RKE2 + PG + RustFS.
# Does not touch Gaius or Marquez. Engines consume via config/metaflow/platform.json.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MANIFEST_DIR="$ROOT/config/k8s/metaflow"

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5455}"
PGUSER="${PGUSER:-signals}"
# Superuser for CREATE ROLE when needed (peer/local often $USER)
PGSUPER="${METAFLOW_PG_SUPERUSER:-$USER}"
MF_DB_USER="${METAFLOW_DB_USER:-metaflow}"
MF_DB_PASS="${METAFLOW_DB_PASSWORD:-metaflow}"
MF_DB_NAME="${METAFLOW_DB_NAME:-metaflow}"
RUSTFS_BUCKET="${METAFLOW_S3_BUCKET:-metaflow}"
NODE_IP="${SIGNALS_NODE_IP:-}"
SERVICE_URL="${METAFLOW_SERVICE_URL:-http://127.0.0.1:30180}"

pick_kubeconfig() {
  local c
  for c in \
    "${KUBECONFIG:-}" \
    "${HOME}/.kube/rke2.yaml" \
    "${HOME}/.kube/config" \
    /etc/rancher/rke2/rke2.yaml; do
    [[ -n "$c" && -r "$c" ]] || continue
    export KUBECONFIG="$c"
    return 0
  done
  export KUBECONFIG="${HOME}/.kube/rke2.yaml"
  return 1
}

info() { echo "metaflow-platform: $*"; }
die() { echo "ERROR: metaflow-platform: $*" >&2; exit 1; }

k() { kubectl --kubeconfig "$KUBECONFIG" "$@"; }

pick_kubeconfig || true
info "KUBECONFIG=$KUBECONFIG"

command -v kubectl >/dev/null || die "kubectl not found"
k get ns >/dev/null 2>&1 || die "cannot reach cluster"

if [[ -z "$NODE_IP" ]]; then
  # Prefer first IPv4 InternalIP (jsonpath may emit multiple).
  NODE_IP="$(k get nodes -o jsonpath='{range .items[0].status.addresses[?(@.type=="InternalIP")]}{.address}{"\n"}{end}' 2>/dev/null \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1 || true)"
fi
[[ -n "$NODE_IP" ]] || NODE_IP="192.168.1.55"
info "NODE_IP=$NODE_IP (host bridge for PG/RustFS)"

# ── Postgres: role + database ─────────────────────────────────────
info "ensuring database $MF_DB_NAME on ${PGHOST}:${PGPORT}"
if command -v psql >/dev/null 2>&1; then
  # Prefer superuser for CREATE; fall back to signals if already granted
  run_psql() {
    local db="$1"; shift
    if PGPASSWORD="${PGPASSWORD:-}" psql -h "$PGHOST" -p "$PGPORT" -U "$PGSUPER" -d "$db" -v ON_ERROR_STOP=1 "$@" 2>/dev/null; then
      return 0
    fi
    PGPASSWORD="${PGPASSWORD:-signals}" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -v ON_ERROR_STOP=1 "$@"
  }

  run_psql postgres -tc "SELECT 1 FROM pg_roles WHERE rolname = '$MF_DB_USER'" | grep -q 1 || \
    run_psql postgres -c "CREATE USER $MF_DB_USER WITH PASSWORD '$MF_DB_PASS'"

  run_psql postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$MF_DB_NAME'" | grep -q 1 || \
    run_psql postgres -c "CREATE DATABASE $MF_DB_NAME OWNER $MF_DB_USER"

  run_psql "$MF_DB_NAME" -c "GRANT ALL ON SCHEMA public TO $MF_DB_USER" 2>/dev/null || true
  info "Postgres ready ($MF_DB_NAME / $MF_DB_USER)"
else
  info "WARN: psql not found — ensure DB $MF_DB_NAME exists manually"
fi

# ── RustFS bucket (path-style dir under data root) ────────────────
# shellcheck source=/dev/null
. "$ROOT/scripts/signals_data_root.sh"
signals_ensure_data_layout 2>/dev/null || true
RUSTFS_DIR="${SIGNALS_RUSTFS_DATA_DIR:-${SIGNALS_DATA_ROOT:-/raid/signals}/rustfs}"
mkdir -p "$RUSTFS_DIR/$RUSTFS_BUCKET"
info "RustFS bucket dir: $RUSTFS_DIR/$RUSTFS_BUCKET"
if command -v mc >/dev/null 2>&1; then
  mc mb --ignore-existing "local/$RUSTFS_BUCKET" 2>/dev/null || true
fi

# ── Manifests ─────────────────────────────────────────────────────
info "applying manifests from $MANIFEST_DIR"
k apply -f "$MANIFEST_DIR/namespace.yaml"
# Patch host bridge IPs
tmp="$(mktemp)"
sed "s/192.168.1.55/${NODE_IP}/g" "$MANIFEST_DIR/host-bridge.yaml" >"$tmp"
k apply -f "$tmp"
rm -f "$tmp"

# Secrets (may be overridden by env)
k apply -f "$MANIFEST_DIR/secret.yaml"
# Optional: live-patch secret from env
k -n metaflow create secret generic metaflow-db \
  --from-literal=MF_METADATA_DB_USER="$MF_DB_USER" \
  --from-literal=MF_METADATA_DB_PSWD="$MF_DB_PASS" \
  --from-literal=MF_METADATA_DB_NAME="$MF_DB_NAME" \
  --dry-run=client -o yaml | k apply -f -

k apply -f "$MANIFEST_DIR/rbac.yaml"
k apply -f "$MANIFEST_DIR/deployment.yaml"
k apply -f "$MANIFEST_DIR/service.yaml"

info "waiting for metaflow-service Available..."
k -n metaflow rollout status deploy/metaflow-service --timeout=180s

# Health
for i in $(seq 1 30); do
  if curl -sf -m 3 "${SERVICE_URL}/ping" >/dev/null 2>&1; then
    info "OK — metadata service ${SERVICE_URL}/ping"
    curl -sS -m 3 "${SERVICE_URL}/ping" || true
    echo
    info "client profile: config/metaflow/platform.json → ~/.metaflowconfig/config.json"
    info "  export METAFLOW_SERVICE_URL=$SERVICE_URL"
    exit 0
  fi
  sleep 2
done

info "pod diagnostics:"
k -n metaflow get pods,svc -o wide || true
k -n metaflow logs -l app.kubernetes.io/name=metaflow-service --tail=40 || true
die "service not healthy at $SERVICE_URL/ping — check PG reachability from pods (pg_hba 10.42.0.0/16) and image pull"
