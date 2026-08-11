#!/usr/bin/env bash
# Clean stop of *this* signals stack + devenv up -d.
# Does NOT kill other devenv projects' Postgres (see signals_port_lattice.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=/dev/null
. "$ROOT/scripts/signals_port_lattice.sh"

info() { echo "stack-reset: $*"; }

info "devenv processes down"
devenv processes down 2>/dev/null || true
sleep 1

# Stop only our postmaster (never foreign :5455 holders)
signals_pg_stop_ours "$ROOT"

# Free *our* non-PG service ports only if held by processes we started
# (name-match common signals binaries — skip if foreign)
free_if_ours() {
  local port="$1" pattern="$2"
  local pid
  pid="$(signals_port_holder_pid "$port" || true)"
  [[ -n "$pid" ]] || return 0
  local cmd
  cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
  case "$cmd" in
    *$pattern*)
      info "free :$port (ours: $pattern pid=$pid)"
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      kill -9 "$pid" 2>/dev/null || true
      ;;
    *)
      info "leave :$port (not matching $pattern): ${cmd:0:80}"
      ;;
  esac
}

free_if_ours 9010 "rustfs"
free_if_ours 8051 "kudu-master"
free_if_ours 8050 "kudu-tserver"
free_if_ours 21010 "atlas"
free_if_ours 21011 "setupProxy\|marquez\|node"
free_if_ours 6080 "ranger"
free_if_ours 9889 "signals-ui"
free_if_ours 25010 "statestored"
free_if_ours 25020 "catalogd"
free_if_ours 25000 "impalad"
free_if_ours 21050 "impalad"

sleep 1

# Claim lattice port (fail if another project holds signals :5455)
signals_pg_port_claim "$ROOT" || exit 1

info "devenv up -d"
exec devenv up -d
