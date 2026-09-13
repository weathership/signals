#!/usr/bin/env bash
# signals-heal: outer safety net for unattended boot / cold-start convergence.
#
# The per-unit Restart=on-failure policies handle units that have them. This
# covers the tail those policies cannot: a foundation whose StartLimit was
# exhausted, or a RemainAfterExit oneshot (engine, c2, polaris, peers) that
# failed once and stays failed forever because it has no Restart=.
#
# 2026-09-13 cold start: engine failed `import grpc` while uv sync was in
# flight; foundation was already active; this script no-op'd "letting Restart
# converge" and the engine never came back.
#
# Healthy signal = signals-refresh.service active. If it is not, reset-failed
# members and `systemctl start signals.target` (does NOT recycle live peers).
set -uo pipefail

WANTS="${SIGNALS_TARGET_WANTS:-/etc/systemd/system/signals.target.wants}"

if systemctl is-active --quiet signals-refresh.service; then
  exit 0   # group verified healthy — nothing to do
fi

reset_failed_members() {
  local u
  systemctl reset-failed \
    signals.service signals-ready.service signals-polaris.service \
    signals-refresh.service signals-engine.service signals-c2.service \
    2>/dev/null || true
  if [[ -d "$WANTS" ]]; then
    for u in "$WANTS"/*; do
      [[ -e "$u" ]] || continue
      u="$(basename "$u")"
      if [[ "$(systemctl is-failed "$u" 2>/dev/null || true)" == "failed" ]]; then
        echo "signals-heal: reset-failed $u"
        systemctl reset-failed "$u" 2>/dev/null || true
      fi
    done
  fi
}

fstate="$(systemctl is-active signals.service 2>/dev/null || true)"
echo "signals-heal: foundation=$fstate refresh=$(systemctl is-active signals-refresh.service 2>/dev/null || true) — reset-failed + start signals.target (live members stay)"
reset_failed_members
systemctl start --no-block signals.target 2>/dev/null || true
exit 0
