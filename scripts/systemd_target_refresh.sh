#!/usr/bin/env bash
# Complete group recycle: stop everything in signals.target, then start it.
# This is the operator refresh. Certainty, not surgical start-only-failed.
#
#   sudo systemctl restart signals.target
#   # or:
#   just signals-restart
#
# reset-failed so a previous atelier/gaius failure is retried, not skipped.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WANTS="${SIGNALS_TARGET_WANTS:-/etc/systemd/system/signals.target.wants}"

info() { echo "signals-restart: $*"; }
die() { echo "ERROR: signals-restart: $*" >&2; exit 1; }

command -v sudo >/dev/null || die "sudo required"

if [[ -d "$WANTS" ]]; then
  mapfile -t UNITS < <(find "$WANTS" -maxdepth 1 -type l -printf '%f\n' | sort)
  if [[ ${#UNITS[@]} -gt 0 ]]; then
    info "reset-failed ${UNITS[*]}"
    sudo systemctl reset-failed "${UNITS[@]}" 2>/dev/null || true
  fi
fi

info "stop signals.target (PartOf= stops every member)"
sudo systemctl stop signals.target

info "start signals.target (full start of every enabled member)"
sudo systemctl start signals.target

# Post-start verify is also a WantedBy= member; run it here so the just
# recipe fails if the group is not actually up.
if [[ -x "$ROOT/scripts/systemd_target_verify.sh" ]]; then
  "$ROOT/scripts/systemd_target_verify.sh"
fi
