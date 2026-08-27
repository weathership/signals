#!/usr/bin/env bash
# Sourceable: resolve the Signals-controlled Python (devenv uv venv). Never system python3.
#
#   . "$ROOT/scripts/signals_python.sh"
#   PY="$(signals_python_path)" || die "…"     # absolute interpreter path (systemd/setsid)
#   signals_py scripts/foo.py …               # run with the venv; `uv run --frozen` fallback
#
# Policy: languages.python (python312 + uv) in devenv.nix owns .devenv/state/venv; scripts,
# readiness oneshots and systemd units must use it so protobuf/grpc/kerberos wheels match
# the lock. A bare `python3` on the host has none of them (signals-ready false WARN, 2026-08-26).
# Override: SIGNALS_PYTHON=/path/to/python.

signals_repo_root() {
  if [[ -n "${SIGNALS_REPO_ROOT:-}" ]]; then
    echo "$SIGNALS_REPO_ROOT"
  else
    cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
  fi
}

signals_python_path() {
  local root py
  if [[ -n "${SIGNALS_PYTHON:-}" ]]; then
    [[ -x "$SIGNALS_PYTHON" ]] && { echo "$SIGNALS_PYTHON"; return 0; }
    echo "signals_python: SIGNALS_PYTHON=$SIGNALS_PYTHON is not executable" >&2
    return 1
  fi
  root="$(signals_repo_root)"
  py="$root/.devenv/state/venv/bin/python"
  if [[ -x "$py" ]]; then
    echo "$py"
    return 0
  fi
  echo "signals_python: devenv venv missing at $py — run: devenv shell (languages.python uv sync)" >&2
  return 1
}

# Run Python from the venv; without a venv fall back to uv with the lock frozen
# (no re-resolve/sync under systemd — native wheels need devenv compilers).
signals_py() {
  local py root
  if py="$(signals_python_path 2>/dev/null)"; then
    "$py" "$@"
    return $?
  fi
  root="$(signals_repo_root)"
  if command -v uv >/dev/null 2>&1; then
    echo "signals_python: no venv — uv run --frozen --no-sync (cd $root)" >&2
    (cd "$root" && uv run --frozen --no-sync python "$@")
    return $?
  fi
  echo "signals_python: no devenv venv and no uv on PATH — refusing system python3" >&2
  return 127
}
