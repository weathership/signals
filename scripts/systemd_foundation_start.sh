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
up_rc=0
/bin/bash -lc "cd \"$ROOT\" && export PATH=\"/usr/local/bin:\$PATH\" && just up" || up_rc=$?

# devenv 2.1's 120 s daemon waiter can return non-zero while the compose is in
# fact coming up (native.sock live, native-manager.pid unwritten — see the
# repair note above). So repair the pid and POLL readiness on BOTH paths: a
# non-zero `just up` here is frequently a false negative, not a dead stack.
repair_native_manager_pid
if [[ "$up_rc" -eq 0 ]]; then
  info "just up OK"
else
  info "just up returned $up_rc — devenv waiter may have timed out; polling readiness before deciding"
fi

# The critical plane converges shortly after `up` returns. Poll rather than
# checking once — the 2026-08-26 boot failed a single post-up check and gave up
# permanently, leaving the whole data plane down with no retry.
POLL_SECS="${FOUNDATION_READY_POLL_SECS:-150}"
_deadline=$(( SECONDS + POLL_SECS ))
while (( SECONDS < _deadline )); do
  if just signals-ready; then
    info "foundation READY"
    exit 0
  fi
  sleep 10
done

if [[ "$up_rc" -eq 0 ]]; then
  # up succeeded, compose still warming — optimistic success. signals-ready /
  # signals-refresh (Restart=on-failure) keep verifying until healthy.
  info "up completed; ready not yet after ${POLL_SECS}s — verify oneshots will converge"
  exit 0
fi

# up genuinely failed and did not converge in the poll window. Fail so systemd
# Restart re-runs the whole start: a fresh `just up` self-cleans stale daemons
# and frees :5455, which recovers a boot-contention daemon-start loss without
# any manual/agent intervention.
info "foundation not ready after up failure + ${POLL_SECS}s poll — failing for systemd Restart"
exit 1
