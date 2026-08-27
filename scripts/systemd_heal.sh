#!/usr/bin/env bash
# signals-heal: outer safety net for unattended boot convergence.
#
# The per-unit Restart=on-failure policies handle transient failures. This
# covers the tail the Restart policies cannot: a foundation whose StartLimit
# was exhausted, or one that exited 0 optimistically while the critical plane
# never actually came up. Runs as root from signals-heal.timer.
#
# Healthy signal = signals-refresh.service active. The verifier
# (systemd_target_verify.sh) only succeeds when every member AND the warehouse
# ingest freshness pass, so its active(exited) state is the authoritative
# "group is healthy" indicator. If the foundation is not active, reset the
# StartLimit counters (so a rate-limited unit can start again) and re-kick the
# target. If the foundation IS active but the verifier hasn't passed yet, do
# nothing — let the existing Restart/poll loops converge without interference.
set -uo pipefail

if systemctl is-active --quiet signals-refresh.service; then
  exit 0   # group verified healthy — nothing to do
fi

fstate="$(systemctl is-active signals.service 2>/dev/null || true)"
if [ "$fstate" != "active" ]; then
  echo "signals-heal: foundation=$fstate, group not verified — reset StartLimit + re-kick signals.target"
  systemctl reset-failed \
    signals.service signals-ready.service signals-polaris.service \
    signals-refresh.service signals-engine.service signals-c2.service 2>/dev/null || true
  systemctl start --no-block signals.target 2>/dev/null || true
else
  echo "signals-heal: foundation active, verifier not yet passed — letting Restart/poll converge"
fi
exit 0
