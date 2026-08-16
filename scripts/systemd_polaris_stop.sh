#!/usr/bin/env bash
# Stop a standalone Polaris started by systemd_polaris_start.sh.
# Does not tear down a live devenv polaris process unless we own the pidfile.
set -euo pipefail

LOG_DIR="${SIGNALS_POLARIS_LOG_DIR:-/tmp/signals-polaris}"
PID_FILE="$LOG_DIR/server.pid"

info() { echo "signals-polaris.service: $*"; }

if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
    info "stopping pid $pid"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 15); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  exit 0
fi

info "no standalone pidfile — leaving devenv polaris alone"
exit 0
