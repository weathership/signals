#!/usr/bin/env bash
# Keep /tmp/krb5cc_impala inside ticket_lifetime. catalogd and impalad re-read
# that cache; kinit of signals@ does not refresh it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$ROOT/.devenv/profile/bin:${PATH:-}"
# shellcheck source=scripts/signals_kerberos.sh
. "$ROOT/scripts/signals_kerberos.sh"
interval="${SIGNALS_IMPALA_KINIT_INTERVAL:-8h}"
while true; do
  if ! signals_impala_kinit "$ROOT"; then
    echo "impala kinit failed; retry in 5m" >&2
    sleep 5m
    continue
  fi
  sleep "$interval"
done
