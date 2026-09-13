#!/usr/bin/env bash
# Elevated cold-start gate (not a smoke).
#
# 1. Script contracts (no lattice taken down).
# 2. Unless SIGNALS_COLD_START_CI_SCRIPTS_ONLY=1: complete group recycle
#    (`just signals-restart`) then `just lattice-ci`.
#
# Requires sudo for the live recycle. This is the routine drill: stop the
# federated group, start it, prove Engine/Status — the 2026-09-13 race
# (systemd spawning against a half-built uv venv) must stay gone.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { echo "signals-cold-start-ci: $*"; }

info "script contracts"
bash "$ROOT/tests/scripts/test_systemd_cold_start.sh"

if [[ "${SIGNALS_COLD_START_CI_SCRIPTS_ONLY:-0}" == "1" ]]; then
  info "SIGNALS_COLD_START_CI_SCRIPTS_ONLY=1 — skip live recycle"
  exit 0
fi

info "live recycle (signals.target stop+start+verify)"
bash "$ROOT/scripts/systemd_target_refresh.sh"
info "lattice-ci"
bash "$ROOT/scripts/lattice_ci.sh"
info "cold-start gate green"
