#!/usr/bin/env bash
# Idempotent oneshot: Signals engine (YuniKorn + Engine Status) on :50551.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=signals_python.sh
. "$ROOT/scripts/signals_python.sh"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"
export SIGNALS_ENGINE_GRPC_PORT="${SIGNALS_ENGINE_GRPC_PORT:-50551}"
export SIGNALS_YK_API_URL="${SIGNALS_YK_API_URL:-http://127.0.0.1:30080}"
export SIGNALS_REPO_ROOT="$ROOT"
export SIGNALS_KRB_HOST="${SIGNALS_KRB_HOST:-tinybox.dev.vista.zndx.org}"
export SIGNALS_ADVERTISE_HOST="${SIGNALS_ADVERTISE_HOST:-$SIGNALS_KRB_HOST}"
export SIGNALS_YK_PROJECTION_ROOT="${SIGNALS_YK_PROJECTION_ROOT:-$ROOT/build/dev}"

LOG_DIR="${SIGNALS_ENGINE_LOG_DIR:-/tmp/signals-engine}"
PID_FILE="$LOG_DIR/unit_server.pid"
LOG_FILE="$LOG_DIR/unit_server.log"
mkdir -p "$LOG_DIR"

info() { echo "signals-engine.service: $*"; }

status_ok() {
  local py
  py="$(signals_python_path 2>/dev/null)" || return 1
  "$py" - <<'PY' 2>/dev/null
import os, sys
sys.path.insert(0, "src")
sys.path.insert(0, "src/signals/engine/generated")
import grpc
from zndx.engine.v1 import engine_pb2, engine_pb2_grpc
port = os.environ.get("SIGNALS_ENGINE_GRPC_PORT", "50551")
ch = grpc.insecure_channel(f"127.0.0.1:{port}")
stub = engine_pb2_grpc.EngineStub(ch)
r = stub.Status(engine_pb2.StatusRequest(), timeout=3)
sys.exit(0 if r.project == "signals" else 1)
PY
}

if status_ok; then
  info "already READY (Engine/Status :${SIGNALS_ENGINE_GRPC_PORT})"
  exit 0
fi

info "starting python -m signals.engine on :${SIGNALS_ENGINE_GRPC_PORT}"
# Signals-controlled Python only (devenv uv venv); never system python3.
PY="$(signals_python_path)" || { info "ERROR: devenv venv missing — run devenv shell (uv sync)"; exit 1; }
setsid env \
  SIGNALS_ENGINE_GRPC_PORT="$SIGNALS_ENGINE_GRPC_PORT" \
  SIGNALS_YK_API_URL="$SIGNALS_YK_API_URL" \
  SIGNALS_REPO_ROOT="$ROOT" \
  SIGNALS_KRB_HOST="$SIGNALS_KRB_HOST" \
  SIGNALS_ADVERTISE_HOST="$SIGNALS_ADVERTISE_HOST" \
  SIGNALS_YK_PROJECTION_ROOT="$SIGNALS_YK_PROJECTION_ROOT" \
  PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" -m signals.engine \
  >>"$LOG_FILE" 2>&1 < /dev/null &
echo $! > "$PID_FILE"

for i in $(seq 1 60); do
  if status_ok; then
    info "Engine/Status ready (iter=$i) pid=$(cat "$PID_FILE")"
    exit 0
  fi
  sleep 1
done
info "timed out waiting for Status on :${SIGNALS_ENGINE_GRPC_PORT}" >&2
info "log: $LOG_FILE" >&2
exit 1
