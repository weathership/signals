#!/usr/bin/env bash
# Idempotent oneshot: Signals C2 HTTP on :50561 (Yield via engine gRPC).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"
export SIGNALS_C2_HTTP_PORT="${SIGNALS_C2_HTTP_PORT:-50561}"
export SIGNALS_PEER_CONTRACT="${SIGNALS_PEER_CONTRACT:-$ROOT/config/platform/peer-contract.json}"
export SIGNALS_REPO_ROOT="$ROOT"

LOG_DIR="${SIGNALS_C2_LOG_DIR:-/tmp/signals-c2}"
PID_FILE="$LOG_DIR/unit_server.pid"
LOG_FILE="$LOG_DIR/unit_server.log"
mkdir -p "$LOG_DIR"

info() { echo "signals-c2.service: $*"; }

status_ok() {
  curl -sf -m 2 "http://127.0.0.1:${SIGNALS_C2_HTTP_PORT}/healthz" >/dev/null
}

if status_ok; then
  info "already READY (C2 HTTP :${SIGNALS_C2_HTTP_PORT})"
  exit 0
fi

info "starting python -m signals.c2 on :${SIGNALS_C2_HTTP_PORT}"
# Prefer the project venv. Bare `uv run` under systemd re-resolves the lock
# and can stall on native wheels (kerberos) with no devenv compilers.
PY="$ROOT/.devenv/state/venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi
setsid env \
  SIGNALS_C2_HTTP_PORT="$SIGNALS_C2_HTTP_PORT" \
  SIGNALS_PEER_CONTRACT="$SIGNALS_PEER_CONTRACT" \
  SIGNALS_REPO_ROOT="$ROOT" \
  PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" -m signals.c2 \
  >>"$LOG_FILE" 2>&1 < /dev/null &
echo $! > "$PID_FILE"

for i in $(seq 1 30); do
  if status_ok; then
    info "C2 ready (iter=$i) pid=$(cat "$PID_FILE")"
    exit 0
  fi
  sleep 1
done
info "timed out waiting for C2 on :${SIGNALS_C2_HTTP_PORT}" >&2
info "log: $LOG_FILE" >&2
exit 1
