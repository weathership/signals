#!/usr/bin/env bash
# Peer-scoped stop for signals-c2 on :50561.
set -euo pipefail
PORT="${SIGNALS_C2_HTTP_PORT:-50561}"
LOG_DIR="${SIGNALS_C2_LOG_DIR:-/tmp/signals-c2}"
PID_FILE="$LOG_DIR/unit_server.pid"

echo "signals-c2.service: peer-scoped stop on :${PORT}"

stop_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  local cmd
  cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
  if [[ "$cmd" != *signals.c2* && "$cmd" != *signals-c2* ]]; then
    return 0
  fi
  echo "signals-c2.service: TERM pid=$pid"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
}

[[ -f "$PID_FILE" ]] && stop_pid "$(cat "$PID_FILE")" && rm -f "$PID_FILE"

if command -v ss >/dev/null 2>&1; then
  for pid in $(ss -ltnp 2>/dev/null | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | sort -u); do
    stop_pid "$pid"
  done
fi
sleep 1
if command -v ss >/dev/null 2>&1; then
  for pid in $(ss -ltnp 2>/dev/null | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | sort -u); do
    cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
    if [[ "$cmd" == *signals.c2* ]]; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
fi
echo "signals-c2.service: stop done"
