#!/usr/bin/env bash
# Idempotent oneshot: Signals engine (YuniKorn + Engine Status) on :50551.
#
# devenv owns the process graph (`just up` / processes.signals-engine). This
# unit is a membership hook: wait for Engine/Status from that compose. Do not
# spawn a second interpreter while uv/devenv is starting the same checkout
# (2026-09-13: systemd raced `uv run` rebuilding the venv; `import grpc` failed
# and heal no-op'd because the foundation was already active).
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
# PromoteScratch's kubectl needs a READABLE kubeconfig; a login shell may
# leak the root-only /etc/rancher/rke2/rke2.yaml (2026-08-28..30 incident).
if [ -r "$HOME/.kube/rke2.yaml" ]; then
  export SIGNALS_YK_KUBECONFIG="${SIGNALS_YK_KUBECONFIG:-$HOME/.kube/rke2.yaml}"
fi

LOG_DIR="${SIGNALS_ENGINE_LOG_DIR:-/tmp/signals-engine}"
PID_FILE="$LOG_DIR/unit_server.pid"
LOG_FILE="$LOG_DIR/unit_server.log"
mkdir -p "$LOG_DIR"

POLL_ITERS="${SIGNALS_ENGINE_POLL_ITERS:-180}"
POLL_SLEEP="${SIGNALS_ENGINE_POLL_SLEEP:-5}"
SPAWNED=0

info() { echo "signals-engine.service: $*"; }

# grpcurl does not need the venv — usable while uv sync is still installing grpc.
status_ok() {
  local port="${SIGNALS_ENGINE_GRPC_PORT:-50551}"
  if command -v grpcurl >/dev/null 2>&1; then
    grpcurl -plaintext -connect-timeout 2 "127.0.0.1:${port}" \
      zndx.engine.v1.Engine/Status >/dev/null 2>&1
    return $?
  fi
  local py
  py="$(signals_python_path 2>/dev/null)" || return 1
  SIGNALS_ENGINE_GRPC_PORT="$port" "$py" - <<'PY' 2>/dev/null
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

spawn_fallback() {
  local py
  py="$(signals_python_path)" || return 1
  info "no devenv supervisor — spawning $py -m signals.engine (test/dev fallback)"
  setsid env \
    SIGNALS_ENGINE_GRPC_PORT="$SIGNALS_ENGINE_GRPC_PORT" \
    SIGNALS_YK_API_URL="$SIGNALS_YK_API_URL" \
    SIGNALS_REPO_ROOT="$SIGNALS_REPO_ROOT" \
    SIGNALS_KRB_HOST="$SIGNALS_KRB_HOST" \
    SIGNALS_ADVERTISE_HOST="$SIGNALS_ADVERTISE_HOST" \
    SIGNALS_YK_PROJECTION_ROOT="$SIGNALS_YK_PROJECTION_ROOT" \
    PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$py" -m signals.engine \
    >>"$LOG_FILE" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"
  SPAWNED=1
}

if status_ok; then
  info "already READY (Engine/Status :${SIGNALS_ENGINE_GRPC_PORT})"
  exit 0
fi

info "waiting for compose-owned Engine/Status on :${SIGNALS_ENGINE_GRPC_PORT}"

for i in $(seq 1 "$POLL_ITERS"); do
  if status_ok; then
    info "Engine/Status ready (iter=$i)"
    exit 0
  fi
  if signals_module_supervisor_running "signals.engine"; then
    if (( i % 6 == 0 )); then
      info "devenv/uv starting this checkout's engine — waiting (iter=$i; will not spawn a second interpreter)"
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
      info "venv not import-ready yet (iter=$i) — waiting for uv sync"
    fi
  fi
  sleep "$POLL_SLEEP"
done

info "timed out waiting for Engine/Status on :${SIGNALS_ENGINE_GRPC_PORT}" >&2
info "log: $LOG_FILE" >&2
info "Guru: compose should own python -m signals.engine; check devenv processes + uv sync" >&2
exit 1
