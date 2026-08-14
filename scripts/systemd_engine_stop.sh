#!/usr/bin/env bash
# Peer-scoped stop for signals-engine on :50551.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${SIGNALS_ENGINE_GRPC_PORT:-50551}"
LOG_DIR="${SIGNALS_ENGINE_LOG_DIR:-/tmp/signals-engine}"
PID_FILE="$LOG_DIR/unit_server.pid"

echo "signals-engine.service: peer-scoped stop on :${PORT}"

stop_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  local cmd
  cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
  if [[ "$cmd" != *signals.engine* && "$cmd" != *signals-engine* ]]; then
    return 0
  fi
  echo "signals-engine.service: TERM pid=$pid"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
}

[[ -f "$PID_FILE" ]] && stop_pid "$(cat "$PID_FILE")" && rm -f "$PID_FILE"

if command -v ss >/dev/null 2>&1; then
  for pid in $(ss -ltnp 2>/dev/null | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | sort -u); do
    stop_pid "$pid"
  done
fi
sleep 2
if command -v ss >/dev/null 2>&1; then
  for pid in $(ss -ltnp 2>/dev/null | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | sort -u); do
    cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
    if [[ "$cmd" == *signals.engine* ]]; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
fi
echo "signals-engine.service: stop done"
