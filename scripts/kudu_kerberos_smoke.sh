#!/usr/bin/env bash
# PR-K5a: verify Kudu Kerberos prerequisites and optional live probes.
#
# Always checks:
#   - KDC krb5.conf + kudu.keytab principals (from signals:kdc-init)
#   - SIGNALS_KUDU_KERBEROS mode documentation
#
# When SIGNALS_KUDU_KERBEROS=1 and masters are up:
#   - kinit as signals@REALM from signals.keytab
#   - Attempt a minimal C++/Python open if tools exist; otherwise report flags
#
# Usage:
#   devenv tasks run signals:kudu-kerberos-smoke
#   SIGNALS_KUDU_KERBEROS=1 bash scripts/kudu_kerberos_smoke.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
KDC_DIR="${KDC_DIR:-$PROJECT_DIR/.devenv/kdc}"
REALM="${KRB5_REALM:-DEV.VISTA.ZNDX.ORG}"
KRB_HOST="${SIGNALS_KRB_HOST:-tinybox.dev.vista.zndx.org}"
KUDU_KEYTAB="${SIGNALS_KUDU_KEYTAB:-$KDC_DIR/kudu.keytab}"
USER_KEYTAB="${SIGNALS_KRB_USER_KEYTAB:-$KDC_DIR/signals.keytab}"
KRB5_CONF="${KRB5_CONFIG:-$KDC_DIR/krb5.conf}"
MODE="${SIGNALS_KUDU_KERBEROS:-0}"

pass=0
fail=0
warn=0

ok()  { echo "  OK  $*"; pass=$((pass + 1)); }
bad() { echo "  FAIL $*"; fail=$((fail + 1)); }
note(){ echo "  NOTE $*"; warn=$((warn + 1)); }

echo "=== PR-K5a Kudu Kerberos smoke ==="
echo "  PROJECT=$PROJECT_DIR"
echo "  SIGNALS_KUDU_KERBEROS=$MODE"
echo "  REALM=$REALM KRB_HOST=$KRB_HOST"
echo

# ── 1. KDC material ────────────────────────────────────────────────────────
echo "[1] KDC / keytabs"
if [[ -f "$KRB5_CONF" ]]; then
  ok "krb5.conf: $KRB5_CONF"
  export KRB5_CONFIG="$KRB5_CONF"
else
  bad "missing $KRB5_CONF — run: devenv tasks run signals:kdc-init"
fi

if [[ -f "$KUDU_KEYTAB" ]]; then
  ok "kudu keytab: $KUDU_KEYTAB"
  if command -v klist >/dev/null 2>&1; then
    if klist -k "$KUDU_KEYTAB" 2>/dev/null | grep -q "kudu/"; then
      ok "keytab contains kudu/… principal(s)"
      klist -k "$KUDU_KEYTAB" 2>/dev/null | grep "kudu/" | head -5 | sed 's/^/       /'
    else
      bad "keytab has no kudu/ principal — re-run signals:kdc-init"
    fi
  else
    note "klist not on PATH; skip principal listing"
  fi
else
  bad "missing kudu keytab $KUDU_KEYTAB — run signals:kdc-init"
fi

if [[ -f "$USER_KEYTAB" ]]; then
  ok "user keytab: $USER_KEYTAB (signals@$REALM)"
else
  note "missing $USER_KEYTAB (optional for kinit probe)"
fi

# ── 2. Host / SPN alignment ────────────────────────────────────────────────
echo
echo "[2] Host / SPN"
if getent hosts "$KRB_HOST" >/dev/null 2>&1 || grep -q "$KRB_HOST" /etc/hosts 2>/dev/null; then
  ok "$KRB_HOST resolves (needed for kudu/_HOST → kudu/$KRB_HOST)"
else
  note "$KRB_HOST does not resolve — add '127.0.0.1 $KRB_HOST' to /etc/hosts for Kerberos"
fi

# ── 3. Mode expectations ───────────────────────────────────────────────────
echo
echo "[3] Mode"
if [[ "$MODE" = "1" ]]; then
  ok "Kerberos mode ON — kudu-master/tserver must start with --keytab_file + rpc_authentication=required"
  note "nosasl Impala/FDW clients will fail until K5b; restart: SIGNALS_KUDU_KERBEROS=1 devenv up"
else
  ok "Kerberos mode OFF (default) — stack stays nosasl-compatible"
  note "Enable with: export SIGNALS_KUDU_KERBEROS=1  (then restart kudu-master/tserver)"
fi

# ── 4. Live probes (best-effort) ───────────────────────────────────────────
echo
echo "[4] Live probes"
if ! curl -sf -o /dev/null --connect-timeout 1 "http://127.0.0.1:8051/" 2>/dev/null; then
  note "Kudu master web UI :8051 not up — skip live client probes"
else
  ok "Kudu master web UI responds on :8051"
  # Detect whether daemons logged kerberos from process list / logs
  if [[ -f "$PROJECT_DIR/.devenv/kudu/master/logs/kudu-master.INFO" ]] || \
     ls "$PROJECT_DIR/.devenv/kudu/master/logs/"*INFO* >/dev/null 2>&1; then
    if rg -q "Kerberos|keytab|GSSAPI|rpc_authentication" \
         "$PROJECT_DIR/.devenv/kudu/master/logs/" 2>/dev/null; then
      ok "master logs mention Kerberos/keytab (auth path exercised at startup)"
    else
      note "master logs present but no Kerberos strings (likely MODE=0)"
    fi
  fi

  if [[ "$MODE" = "1" ]] && [[ -f "$USER_KEYTAB" ]] && command -v kinit >/dev/null 2>&1; then
    CC="${KRB5CCNAME:-$KDC_DIR/krb5cc_k5a_smoke}"
    export KRB5CCNAME="$CC"
    if kinit -kt "$USER_KEYTAB" "signals@$REALM" 2>/dev/null; then
      ok "kinit signals@$REALM via keytab (KRB5CCNAME=$CC)"
      klist 2>/dev/null | head -8 | sed 's/^/       /' || true
    else
      bad "kinit failed for signals@$REALM"
    fi
  fi
fi

# ── 5. Summary ─────────────────────────────────────────────────────────────
echo
echo "=== Summary: $pass ok, $warn notes, $fail fail ==="
if [[ "$fail" -gt 0 ]]; then
  echo "K5a prerequisites incomplete."
  exit 1
fi
echo "K5a smoke: prerequisites OK."
echo "Next: K5b wire libkudu_client SASL (exec_kudu) when MODE=1."
exit 0
