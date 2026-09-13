#!/usr/bin/env bash
# Contract tests for cold-start unit scripts. No project venv, no live lattice.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=../../scripts/signals_python.sh
. "$ROOT/scripts/signals_python.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "OK   $*"; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# --- signals_python_path: missing ---
export SIGNALS_REPO_ROOT="$tmp/missing-root"
export SIGNALS_PYTHON=""
unset SIGNALS_PYTHON
mkdir -p "$SIGNALS_REPO_ROOT"
rc=0
SIGNALS_REPO_ROOT="$SIGNALS_REPO_ROOT" signals_python_path >/dev/null 2>"$tmp/err" || rc=$?
[[ "$rc" -eq 1 ]] || fail "missing venv rc=$rc want 1 (stderr=$(cat "$tmp/err"))"
pass "missing venv returns 1"

# --- exists but cannot import grpc ---
incomplete="$tmp/incomplete"
mkdir -p "$incomplete"
cat > "$incomplete/python" <<'PY'
#!/usr/bin/env python3
import sys
sys.exit(1)
PY
chmod +x "$incomplete/python"
rc=0
SIGNALS_PYTHON="$incomplete/python" signals_python_path >/dev/null 2>"$tmp/err" || rc=$?
[[ "$rc" -eq 2 ]] || fail "incomplete venv rc=$rc want 2 (stderr=$(cat "$tmp/err"))"
grep -q 'cannot import grpc' "$tmp/err" || fail "incomplete venv should mention grpc"
pass "incomplete venv returns 2"

# --- import-ready ---
ready="$tmp/ready"
mkdir -p "$ready"
cat > "$ready/python" <<'PY'
#!/usr/bin/env python3
import sys
sys.exit(0)
PY
chmod +x "$ready/python"
out="$(SIGNALS_PYTHON="$ready/python" signals_python_path)" || fail "ready interpreter should succeed"
[[ "$out" == "$ready/python" ]] || fail "ready path $out"
pass "import-ready interpreter is returned"

# --- supervisor: python -m <module> with cwd == repo ---
# Use a throwaway module name and a tiny HTTP server so we do not touch :50551.
port=18765
SIGNALS_REPO_ROOT="$ROOT"
python3 -m http.server "$port" --bind 127.0.0.1 >/dev/null 2>&1 &
http_pid=$!
trap 'kill $http_pid 2>/dev/null || true; rm -rf "$tmp"' EXIT
for _ in $(seq 1 20); do
  kill -0 "$http_pid" 2>/dev/null || fail "http.server died"
  # cwd of the child should be ROOT because we started it here
  if [[ "$(readlink "/proc/$http_pid/cwd" 2>/dev/null || true)" == "$ROOT" ]]; then
    break
  fi
  sleep 0.1
done
SIGNALS_REPO_ROOT="$ROOT"
signals_module_supervisor_running "http.server" || fail "should see python -m http.server in this checkout"
if signals_module_supervisor_running "signals.engine"; then
  # Live lattice may have a real engine — that is still a correct match.
  pass "signals.engine supervisor present (live compose) — contract still holds"
else
  pass "signals.engine supervisor absent (no false positive from http.server)"
fi
kill "$http_pid" 2>/dev/null || true
wait "$http_pid" 2>/dev/null || true
trap 'rm -rf "$tmp"' EXIT
pass "supervisor matches cwd+module"

# --- heal: refresh inactive → start signals.target (live members stay) ---
fake="$tmp/fakebin"
mkdir -p "$fake" "$tmp/wants"
ln -s /dev/null "$tmp/wants/signals-engine.service"
cat > "$fake/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "systemctl $*" >> "${HEAL_LOG}"
case "$1" in
  is-active)
    if [[ "$2" == "--quiet" ]]; then
      exit 1
    fi
    if [[ "$2" == "signals.service" ]]; then
      echo active
      exit 0
    fi
    echo inactive
    exit 3
    ;;
  "is-failed")
    if [[ "$2" == "signals-engine.service" ]]; then
      echo failed
      exit 0
    fi
    echo inactive
    exit 1
    ;;
  "reset-failed")
    exit 0
    ;;
  "start --no-block")
    exit 0
    ;;
  start)
    exit 0
    ;;
esac
exit 0
EOF
chmod +x "$fake/systemctl"
HEAL_LOG="$tmp/heal.log"
export HEAL_LOG
: > "$HEAL_LOG"
PATH="$fake:$PATH" SIGNALS_TARGET_WANTS="$tmp/wants" \
  bash "$ROOT/scripts/systemd_heal.sh" >/dev/null
grep -q 'start --no-block signals.target' "$HEAL_LOG" \
  || fail "heal should start signals.target when refresh is down: $(cat "$HEAL_LOG")"
grep -q 'reset-failed signals-engine.service' "$HEAL_LOG" \
  || fail "heal should reset-failed the failed engine: $(cat "$HEAL_LOG")"
pass "heal re-kicks target and reset-failed engine when refresh is down"

# --- heal: refresh active → no-op ---
cat > "$fake/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "systemctl $*" >> "${HEAL_LOG}"
if [[ "$1" == "is-active" && "$2" == "--quiet" ]]; then
  exit 0
fi
exit 0
EOF
chmod +x "$fake/systemctl"
: > "$HEAL_LOG"
PATH="$fake:$PATH" bash "$ROOT/scripts/systemd_heal.sh" >/dev/null
if grep -q 'start ' "$HEAL_LOG"; then
  fail "heal should no-op when refresh is active: $(cat "$HEAL_LOG")"
fi
pass "heal no-ops when refresh is active"

echo "ALL OK"
