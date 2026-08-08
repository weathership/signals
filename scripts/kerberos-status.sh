#!/usr/bin/env bash
# Show Kerberos + data-plane auth status.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/signals_kerberos.sh
source "$ROOT/scripts/signals_kerberos.sh"
signals_krb_env "$ROOT"

echo "Kerberos status (required — no NOSASL path)"
echo "  KRB5_CONFIG=$KRB5_CONFIG"
echo "  KRB5CCNAME=$KRB5CCNAME"
echo "  SIGNALS_KRB_HOST=$SIGNALS_KRB_HOST"
echo "  IMPALA_HS2_HOST=$IMPALA_HS2_HOST:$IMPALA_HS2_PORT"
echo "  principal: $SIGNALS_USER_PRINCIPAL / $SIGNALS_IMPALA_PRINCIPAL"

if signals_krb_hosts_ok "$ROOT"; then
  echo "  hosts: $SIGNALS_KRB_HOST → $(getent hosts "$SIGNALS_KRB_HOST" | awk '{print $1}')"
else
  echo "  hosts: FAIL ($SIGNALS_KRB_HOST does not resolve)"
fi

if signals_krb_ticket_ok "$ROOT"; then
  echo "  ticket: OK"
  klist 2>/dev/null | head -6 | sed 's/^/    /'
else
  echo "  ticket: MISSING — run: just kinit"
fi

# Process probes
if curl -sf -o /dev/null "http://127.0.0.1:8051/"; then
  echo "  kudu-master: up (web)"
else
  echo "  kudu-master: down"
fi
if curl -sf -o /dev/null "http://127.0.0.1:25000/"; then
  echo "  impalad: up (web)"
else
  echo "  impalad: down"
fi

# GSSAPI HS2
if command -v uv >/dev/null 2>&1; then
  if uv run python "$ROOT/scripts/impala_query.py" --probe -q 'SELECT 1' 2>/dev/null; then
    echo "  impala HS2: GSSAPI OK ($IMPALA_HS2_HOST:$IMPALA_HS2_PORT)"
  else
    echo "  impala HS2: GSSAPI FAIL (just bootstrap && devenv up -d)"
  fi
else
  echo "  impala HS2: skip probe (uv not available)"
fi
