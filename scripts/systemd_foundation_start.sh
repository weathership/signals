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

info "not ready — just up (login shell for direnv/devenv/nix)"
# Full user environment: devenv is not on bare systemd PATH.
if /bin/bash -lc "cd \"$ROOT\" && export PATH=\"/usr/local/bin:\$PATH\" && just up"; then
  info "just up OK"
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
