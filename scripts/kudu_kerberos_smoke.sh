#!/usr/bin/env bash
# PR-K5a: verify Kudu Kerberos keytab + principals (Kerberos required).
#
#   just kudu-kerberos-smoke
#   devenv tasks run signals:kudu-kerberos-smoke
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/signals_kerberos.sh
source "$ROOT/scripts/signals_kerberos.sh"
signals_krb_env "$ROOT"

ok() { echo "  ok: $*"; }
bad() { echo "  FAIL: $*"; exit 1; }
note() { echo "  note: $*"; }

echo "Kudu Kerberos smoke (required auth path)"
echo "  SIGNALS_KRB_HOST=$SIGNALS_KRB_HOST"
echo "  keytab=$SIGNALS_KUDU_KEYTAB"

if [ ! -f "$SIGNALS_KUDU_KEYTAB" ]; then
  bad "missing $SIGNALS_KUDU_KEYTAB — just bootstrap"
fi

if command -v klist >/dev/null 2>&1; then
  if klist -kt "$SIGNALS_KUDU_KEYTAB" 2>/dev/null | grep -q "kudu/"; then
    ok "keytab contains kudu/… principal(s)"
    klist -kt "$SIGNALS_KUDU_KEYTAB" | sed 's/^/    /'
  else
    bad "keytab has no kudu/ principal — re-run just bootstrap / signals:kdc-init"
  fi
else
  note "klist not on PATH; skip principal listing"
fi

if signals_krb_hosts_ok "$ROOT"; then
  ok "$SIGNALS_KRB_HOST resolves"
else
  bad "$SIGNALS_KRB_HOST does not resolve"
fi

if curl -sf -o /dev/null "http://127.0.0.1:8051/"; then
  ok "kudu-master web up"
  if command -v rg >/dev/null 2>&1; then
    if ps aux 2>/dev/null | rg -q "kudu-master.*--principal=kudu/"; then
      ok "kudu-master running with --principal=kudu/…"
    else
      bad "kudu-master not running with Kerberos principal — devenv up -d after just bootstrap"
    fi
  fi
else
  note "kudu-master not up (start with devenv up -d)"
fi

echo "Kudu Kerberos smoke done."
