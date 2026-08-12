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
    exit 0
  fi
  echo "systemd-signals-ready: waiting (attempt $i/$MAX)…"
  sleep "$SLEEP"
done

echo "systemd-signals-ready: timed out" >&2
exit 1
