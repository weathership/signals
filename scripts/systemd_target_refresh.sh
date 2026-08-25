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

# A refresh is a complete recycle: every member must leave and come back.
# Record when each member last became active so the recycle can be proved,
# not assumed — on 2026-08-25 `stop signals.target` recycled the peers but the
# foundation's stop never ran, leaving boot-time Kudu/Impala/Postgres running
# under a freshly rebuilt jar. That looked like a successful refresh and was not.
declare -A BEFORE
for u in "${UNITS[@]:-}"; do
  [[ -n "$u" ]] || continue
  BEFORE["$u"]=$(systemctl show "$u" -p ActiveEnterTimestampMonotonic --value 2>/dev/null || echo 0)
done

info "stop signals.target (PartOf= stops every member)"
sudo systemctl stop signals.target
# The foundation is ordered to stop last; stop it explicitly and wait until it
# is inactive so the start below cannot merge over a still-queued stop.
info "stop signals.service (foundation, explicit)"
sudo systemctl stop signals.service
for _ in $(seq 1 90); do
  st=$(systemctl is-active signals.service 2>/dev/null || true)
  [[ "$st" == "inactive" || "$st" == "failed" ]] && break
  sleep 1
done
info "foundation is-active=$(systemctl is-active signals.service 2>/dev/null || true)"

info "start signals.target (full start of every enabled member)"
sudo systemctl start signals.target

not_recycled=""
for u in "${UNITS[@]:-}"; do
  [[ -n "$u" ]] || continue
  [[ "$u" == "signals-refresh.service" ]] && continue
  after=$(systemctl show "$u" -p ActiveEnterTimestampMonotonic --value 2>/dev/null || echo 0)
  if [[ "${after:-0}" -le "${BEFORE[$u]:-0}" ]]; then
    not_recycled="$not_recycled $u"
  fi
done
if [[ -n "$not_recycled" ]]; then
  die "members NOT recycled (ActiveEnterTimestamp unchanged):$not_recycled — refresh incomplete. Guru: #SL.00000031.NOTRECYCLED"
fi
info "every member recycled"

# Post-start verify is also a WantedBy= member; run it here so the just
# recipe fails if the group is not actually up.
if [[ -x "$ROOT/scripts/systemd_target_verify.sh" ]]; then
  "$ROOT/scripts/systemd_target_verify.sh"
fi
