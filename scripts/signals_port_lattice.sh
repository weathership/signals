#!/usr/bin/env bash
# Lab-wide loopback Postgres port lattice (tinybox multi-devenv host).
#
#   cybersec / cyberphy … 5438
#   gaius ………………… 5444
#   signals ……………… 5455   ← this tree
#   atelier ……………… 5533
#   aegir ………………… 5555
#   synth ………………… 5566
#   system apt PG ……… 5432   (not devenv; leave alone)
#
# Never silently steal another project's port. Never kill a foreign postmaster.
# shellcheck shell=bash

signals_pg_port() {
  echo "${SIGNALS_PG_PORT:-${PGPORT:-5455}}"
}

signals_port_lattice_print() {
  cat <<'EOF'
Lab Postgres loopback lattice (do not collide):
  5432  system/apt PostgreSQL (if present)
  5438  cybersec / cyberphy
  5444  gaius
  5455  signals  (this project)
  5533  atelier
  5555  aegir
  5566  synth
EOF
}

# Return 0 if TCP port is free on 127.0.0.1
signals_port_free() {
  local port="$1"
  ! ss -ltn 2>/dev/null | grep -qE ":${port}\\s"
}

# PID listening on TCP port (best-effort)
signals_port_holder_pid() {
  local port="$1"
  ss -ltnp 2>/dev/null | awk -v p=":${port}" '
    index($0, p) {
      if (match($0, /pid=[0-9]+/)) {
        print substr($0, RSTART+4, RLENGTH-4)
        exit
      }
    }'
}

# True if pid is *this* signals devenv postgres (data dir under $root/.devenv/state/postgres)
signals_is_our_postgres_pid() {
  local root="${1:-.}" pid="$2"
  [[ -n "$pid" ]] || return 1
  local cmd
  cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
  [[ -n "$cmd" ]] || return 1
  # Our nix postgres + our state dir, or matching postmaster.pid
  if [[ -f "$root/.devenv/state/postgres/postmaster.pid" ]]; then
    local ours
    ours=$(head -1 "$root/.devenv/state/postgres/postmaster.pid" 2>/dev/null || true)
    [[ "$ours" == "$pid" ]] && return 0
  fi
  case "$cmd" in
    *"$root/.devenv/state/postgres"*|*signals*/.devenv/state/postgres*) return 0 ;;
  esac
  # nix store postgres without our data dir → not ours
  return 1
}

# Claim signals PG port for this tree. Exit 1 if a foreign process holds it.
# Usage: signals_pg_port_claim [root]
signals_pg_port_claim() {
  local root="${1:-${DEVENV_ROOT:-$PWD}}"
  local port
  port="$(signals_pg_port)"
  if signals_port_free "$port"; then
    echo "port-lattice: OK  signals Postgres :${port} free (will bind here)"
    return 0
  fi
  local pid
  pid="$(signals_port_holder_pid "$port" || true)"
  if signals_is_our_postgres_pid "$root" "$pid"; then
    echo "port-lattice: OK  :${port} held by this signals postmaster (pid=${pid:-?})"
    return 0
  fi
  local cmd
  cmd=$(ps -p "${pid:-0}" -o args= 2>/dev/null || echo "<unknown>")
  echo "ERROR: port-lattice: 127.0.0.1:${port} is in use by another process (not this signals tree)." >&2
  echo "  pid=${pid:-?}  cmd=${cmd}" >&2
  echo "  Signals owns :5455 in the lab lattice. Another devenv (e.g. aura2ranger) may be mis-bound." >&2
  signals_port_lattice_print >&2
  echo "  Fix: stop the other stack, or set SIGNALS_PG_PORT only if you also rewire all JDBC/psql callers." >&2
  return 1
}

# Stop only *our* signals postmaster (via postmaster.pid). Never kill foreign.
signals_pg_stop_ours() {
  local root="${1:-${DEVENV_ROOT:-$PWD}}"
  local pidfile="$root/.devenv/state/postgres/postmaster.pid"
  [[ -f "$pidfile" ]] || return 0
  local pid
  pid=$(head -1 "$pidfile" 2>/dev/null || true)
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    if signals_is_our_postgres_pid "$root" "$pid"; then
      echo "port-lattice: stopping our postmaster pid=$pid"
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    else
      echo "port-lattice: postmaster.pid=$pid is not our process — leaving alone" >&2
      return 0
    fi
  fi
  # Only remove pidfile if process is gone
  if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pidfile"
  elif [[ -z "$pid" ]]; then
    rm -f "$pidfile"
  fi
}
