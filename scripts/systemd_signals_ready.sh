#!/usr/bin/env bash
# Poll just signals-ready until exit 0 (signals-ready.service).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"

MAX="${SIGNALS_READY_SYSTEMD_ATTEMPTS:-120}"
SLEEP="${SIGNALS_READY_SYSTEMD_SLEEP:-10}"

# After a host reboot rke2-server can still be activating while this
# oneshot starts. Airflow :30800 / YK / Eventing are K8s; do not poll
# the critical plane until the server unit is active.
for i in $(seq 1 90); do
  if systemctl is-active --quiet rke2-server 2>/dev/null; then
    echo "systemd-signals-ready: rke2-server active"
    break
  fi
  if [[ "$i" -eq 90 ]]; then
    echo "systemd-signals-ready: rke2-server not active after wait" >&2
    systemctl is-active rke2-server >&2 || true
    exit 1
  fi
  echo "systemd-signals-ready: waiting for rke2-server (attempt $i/90)"
  sleep 5
done

for i in $(seq 1 "$MAX"); do
  if just signals-ready; then
    echo "systemd-signals-ready: READY (attempt $i)"
    # Warm the varnish-fronted waffle roster: the malloc store is empty
    # after a restart. Fire-and-forget; the public route primes the cache.
    (
      sleep 5
      curl -sf --max-time 60 -o /dev/null \
        "http://127.0.0.1:9889/api/signals/v1/federation/surfaces" || true
    ) >/dev/null 2>&1 &
    exit 0
  fi
  echo "systemd-signals-ready: waiting (attempt $i/$MAX)…"
  sleep "$SLEEP"
done

echo "systemd-signals-ready: timed out" >&2
exit 1
