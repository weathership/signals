#!/usr/bin/env bash
# just rebuild — Metabase-style host product loop for Signals Polaris.
#
#   1) build Polarisfork from components/polaris → .devenv/polaris
#   2) restart polaris (+ polaris-init) under devenv, or devenv up -d
#   3) wait until :8182/q/health/ready
#
# SKIP_POLARIS_BUILD=1  — restart only (deny if no installed server jar)
# Not just redeploy (K8s). Not Metabase just rebuild (AGPL tree).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { echo "rebuild: $*"; }
die() { echo "ERROR: rebuild: $*" >&2; exit 1; }

POLARIS_HOME="${POLARIS_HOME:-$ROOT/.devenv/polaris}"
ADMIN="http://127.0.0.1:8182/q/health/ready"

polaris_installed() {
  [[ -f "$POLARIS_HOME/polaris-quarkus-server.jar" || -f "$POLARIS_HOME/server/quarkus-run.jar" ]]
}

polaris_ready() {
  curl -sf -m 3 "$ADMIN" >/dev/null 2>&1
}

echo "══ just rebuild (Polaris + host catalog) ══════════════════"

if [[ "${SKIP_POLARIS_BUILD:-0}" == "1" ]]; then
  info "SKIP_POLARIS_BUILD=1 — not assembling Polarisfork"
  polaris_installed || die "no Polarisfork install — run without SKIP_POLARIS_BUILD"
else
  info "polaris:install from components/polaris"
  devenv tasks run polaris:install
fi

if devenv processes list >/dev/null 2>&1; then
  info "process manager up — restart polaris"
  devenv processes restart polaris 2>/dev/null || devenv processes start polaris
  devenv processes start polaris-init 2>/dev/null || true
else
  info "process manager not running — devenv up -d"
  devenv up -d
fi

info "waiting for $ADMIN"
ok=0
for i in $(seq 1 90); do
  if polaris_ready; then
    ok=1
    info "Polaris healthy after ~$((i * 2))s"
    break
  fi
  if (( i % 15 == 0 )); then
    info "still waiting (${i}/90)…"
  fi
  sleep 2
done

if [[ "$ok" != "1" ]]; then
  die "Polaris never became ready on :8182 — devenv processes logs polaris"
fi

if [[ -x "$ROOT/scripts/setup_polaris_catalog.sh" ]]; then
  info "ensure catalog signals → s3://signals-dataproducts/iceberg"
  "$ROOT/scripts/setup_polaris_catalog.sh" || info "catalog apply note (already present or Polarisfork still settling)"
fi

echo "══ rebuild complete ══════════════════════════════════════"
echo "  REST   http://127.0.0.1:8181"
echo "  admin  http://127.0.0.1:8182"
echo "  SoR    Iceberg on RustFS (not pglite)"
