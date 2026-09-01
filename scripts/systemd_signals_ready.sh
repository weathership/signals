#!/usr/bin/env bash
# Poll just signals-ready until exit 0 (signals-ready.service).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"

MAX="${SIGNALS_READY_SYSTEMD_ATTEMPTS:-120}"
SLEEP="${SIGNALS_READY_SYSTEMD_SLEEP:-10}"

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
