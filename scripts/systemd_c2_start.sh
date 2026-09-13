#!/usr/bin/env bash
# Idempotent oneshot: Signals C2 HTTP on :50561 (Yield via engine gRPC).
#
# Same membership-hook rule as the engine: devenv owns processes.signals-c2.
# Wait for /healthz; do not spawn a second interpreter while compose is up.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=signals_python.sh
. "$ROOT/scripts/signals_python.sh"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"
export SIGNALS_C2_HTTP_PORT="${SIGNALS_C2_HTTP_PORT:-50561}"
export SIGNALS_PEER_CONTRACT="${SIGNALS_PEER_CONTRACT:-$ROOT/config/platform/peer-contract.json}"
export SIGNALS_REPO_ROOT="$ROOT"

LOG_DIR="${SIGNALS_C2_LOG_DIR:-/tmp/signals-c2}"
PID_FILE="$LOG_DIR/unit_server.pid"
LOG_FILE="$LOG_DIR/unit_server.log"
mkdir -p "$LOG_DIR"

POLL_ITERS="${SIGNALS_C2_POLL_ITERS:-36}"
POLL_SLEEP="${SIGNALS_C2_POLL_SLEEP:-5}"
SPAWNED=0

info() { echo "signals-c2.service: $*"; }

status_ok() {
  curl -sf -m 2 "http://127.0.0.1:${SIGNALS_C2_HTTP_PORT}/healthz" >/dev/null
}

spawn_fallback() {
  local py
  py="$(signals_python_path)" || return 1
  info "no devenv supervisor — spawning $py -m signals.c2 (test/dev fallback)"
  setsid env \
    SIGNALS_C2_HTTP_PORT="$SIGNALS_C2_HTTP_PORT" \
    SIGNALS_PEER_CONTRACT="$SIGNALS_PEER_CONTRACT" \
    SIGNALS_REPO_ROOT="$SIGNALS_REPO_ROOT" \
    PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$py" -m signals.c2 \
    >>"$LOG_FILE" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"
  SPAWNED=1
}

if status_ok; then
  info "already READY (C2 HTTP :${SIGNALS_C2_HTTP_PORT})"
  exit 0
fi

info "waiting for compose-owned C2 on :${SIGNALS_C2_HTTP_PORT}"

for i in $(seq 1 "$POLL_ITERS"); do
  if status_ok; then
    info "C2 ready (iter=$i)"
    exit 0
  fi
  if signals_module_supervisor_running "signals.c2"; then
    if (( i % 6 == 0 )); then
      info "devenv/uv starting this checkout's C2 — waiting (iter=$i; will not spawn a second interpreter)"
    fi
    sleep "$POLL_SLEEP"
    continue
  fi
  if [[ "$SPAWNED" -eq 0 ]]; then
    if spawn_fallback; then
      sleep "$POLL_SLEEP"
      continue
    fi
    if (( i % 6 == 0 )); then
      info "venv not import-ready yet (iter=$i) — waiting"
    fi
  fi
  sleep "$POLL_SLEEP"
done

info "timed out waiting for C2 on :${SIGNALS_C2_HTTP_PORT}" >&2
info "log: $LOG_FILE" >&2
exit 1
