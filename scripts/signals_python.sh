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
#
# The interpreter path is not enough: a half-built venv (uv sync in flight) has a
# `python` binary that cannot import grpc. Return 2 in that case so callers wait
# rather than spawn a second engine against the lock (2026-09-13 cold start).

signals_repo_root() {
  if [[ -n "${SIGNALS_REPO_ROOT:-}" ]]; then
    echo "$SIGNALS_REPO_ROOT"
  else
    cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
  fi
}

# Sentinel import: lattice scripts/engine/c2 all need grpc. Keep this cheap.
signals_python_import_ok() {
  local py="$1"
  [[ -n "$py" && -x "$py" ]] || return 1
  "$py" -c 'import grpc' >/dev/null 2>&1
}

signals_python_path() {
  local root py
  if [[ -n "${SIGNALS_PYTHON:-}" ]]; then
    if [[ ! -x "$SIGNALS_PYTHON" ]]; then
      echo "signals_python: SIGNALS_PYTHON=$SIGNALS_PYTHON is not executable" >&2
      return 1
    fi
    if ! signals_python_import_ok "$SIGNALS_PYTHON"; then
      echo "signals_python: SIGNALS_PYTHON=$SIGNALS_PYTHON cannot import grpc (venv incomplete or uv sync in flight)" >&2
      return 2
    fi
    echo "$SIGNALS_PYTHON"
    return 0
  fi
  root="$(signals_repo_root)"
  py="$root/.devenv/state/venv/bin/python"
  if [[ -x "$py" ]]; then
    if ! signals_python_import_ok "$py"; then
      echo "signals_python: $py cannot import grpc (venv incomplete or uv sync in flight)" >&2
      return 2
    fi
    echo "$py"
    return 0
  fi
  echo "signals_python: devenv venv missing at $py — run: devenv shell (languages.python uv sync)" >&2
  return 1
}

# True when this checkout already has a process running `python -m <module>`
# (including `uv run python -m <module>`). Used so systemd does not spawn a
# second interpreter while devenv owns the graph.
signals_module_supervisor_running() {
  local module="$1" root pid cmd cwd
  [[ -n "$module" ]] || return 1
  root="$(signals_repo_root)"
  while read -r pid cmd; do
    case "$cmd" in
      *"-m ${module}"*) ;;
      *) continue ;;
    esac
    cwd="$(readlink "/proc/${pid}/cwd" 2>/dev/null || true)"
    [[ "$cwd" == "$root" ]] || continue
    return 0
  done < <(ps -eo pid=,args=)
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
