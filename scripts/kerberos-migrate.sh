#!/usr/bin/env bash
# just bootstrap — required Kerberos layout for the Signals stack.
# (Formerly "migrate from NOSASL"; there is no NOSASL product path.)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/signals_kerberos.sh
source "$ROOT/scripts/signals_kerberos.sh"

echo "════════════════════════════════════════════════════════════"
echo " Kerberos bootstrap (required)"
echo "════════════════════════════════════════════════════════════"

signals_krb_bootstrap "$ROOT" || exit 1

echo ""
echo "Next:"
echo "  devenv up -d"
echo "  just kerberos-status   # expect GSSAPI OK"
echo "  just backup            # full portable path"
echo "════════════════════════════════════════════════════════════"
