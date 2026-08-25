#!/usr/bin/env bash
# Idempotent foundation start for signals.service (systemd).
# If the critical plane is already ready (e.g. prior devenv up), succeed.
# Otherwise run just up; on conflict with live lattice PG, re-check ready.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"

info() { echo "systemd-foundation: $*"; }

if just signals-ready; then
  info "already READY — skip just up"
  exit 0
fi

# devenv 2.1 can start daemon-processes + native.sock and then time out its
# 120 s waiter before writing native-manager.pid. A later login-shell
# `devenv processes …` then finds no pid file, calls the socket stale, and
# unlinks it — after which nothing can reach a perfectly live compose and
# `just down` stops nothing (the 2026-08-25 split surface). Write the pid
# ourselves, matching the daemon by cwd, before anything else looks.
repair_native_manager_pid() {
  local pid cmd dir have
  while read -r pid cmd; do
    [[ "$cmd" == *devenv-wrapped*daemon-processes* ]] || continue
    [[ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" == "$ROOT" ]] || continue
    dir="${cmd##* }"; dir="${dir%/daemon-config.json}"
    [[ -d "$dir" ]] || continue
    have=$(cat "$dir/native-manager.pid" 2>/dev/null || true)
    if [[ "$have" != "$pid" ]]; then
      printf '%s\n' "$pid" > "$dir/native-manager.pid"
      info "repair native-manager.pid=$pid in $dir"
    fi
  done < <(ps -eo pid=,args=)
}

info "not ready — just up (login shell for direnv/devenv/nix)"
# Full user environment: devenv is not on bare systemd PATH.
if /bin/bash -lc "cd \"$ROOT\" && export PATH=\"/usr/local/bin:\$PATH\" && just up"; then
  info "just up OK"
  repair_native_manager_pid
  # Allow processes a moment; ready oneshot will poll hard
  if just signals-ready; then
    exit 0
  fi
  info "up completed; ready not yet — peer oneshot will poll"
  exit 0
fi

info "just up failed — checking whether foundation is already healthy (e.g. live :5455)"
# Common lab case: stack was started outside systemd; strictPorts rejects second up.
if just signals-ready; then
  info "foundation READY despite up failure — treating as success"
  exit 0
fi

info "foundation still not ready after up failure"
exit 1
