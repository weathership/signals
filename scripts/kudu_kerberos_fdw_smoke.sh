#!/usr/bin/env bash
# PR-K5c: forced kudu_scan as signals@REALM against Kerberos-required Kudu.
#
# Prerequisites:
#   SIGNALS_KUDU_KERBEROS=1 and kudu-master/tserver with
#     --principal=kudu/$SIGNALS_KRB_HOST  (explicit; not kudu/_HOST → uname)
#   impala_fdw with K5b/K5c (SASL + EXPLAIN Principal)
#   Atlas FTs present (config/atlas/kudu_projections_fdw.sql)
#
# Kerberos SPN rule (critical):
#   Client builds SPN as kudu/<host-from-kudu_masters>. Using 127.0.0.1 yields
#   kudu/127.0.0.1 which is NOT in the KDC. Masters must be:
#     $SIGNALS_KRB_HOST:7051
#   and that hostname must resolve to the Kudu RPC address (lab: 127.0.0.1).
#
# Usage:
#   SIGNALS_KUDU_KERBEROS=1 bash scripts/kudu_kerberos_fdw_smoke.sh
#
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KDC_DIR="${KDC_DIR:-$PROJECT_DIR/.devenv/kdc}"
REALM="${KRB5_REALM:-DEV.VISTA.ZNDX.ORG}"
KRB_HOST="${SIGNALS_KRB_HOST:-tinybox.dev.vista.zndx.org}"
USER_KEYTAB="${SIGNALS_KRB_USER_KEYTAB:-$KDC_DIR/signals.keytab}"
export KRB5_CONFIG="${KRB5_CONFIG:-$KDC_DIR/krb5.conf}"
export KRB5CCNAME="${KRB5CCNAME:-$KDC_DIR/krb5cc_k5c_fdw}"
export SIGNALS_KRB_USER_KEYTAB="$USER_KEYTAB"

MASTERS="${KUDU_MASTERS:-${KRB_HOST}:7051}"
PRINCIPAL="signals@${REALM}"

MODE="${SIGNALS_KUDU_KERBEROS:-0}"
if [[ "$MODE" != "1" ]]; then
  echo "WARN: SIGNALS_KUDU_KERBEROS=$MODE — set to 1 and restart Kudu for required auth."
fi

echo "=== K5c FDW Kerberos smoke ==="
echo "  KRB_HOST=$KRB_HOST  MASTERS=$MASTERS  PRINCIPAL=$PRINCIPAL"
echo "  KRB5CCNAME=$KRB5CCNAME  KEYTAB=$USER_KEYTAB"

# ── resolve SPN host to a reachable Kudu address ──────────────────────────
resolve_ip() {
  getent ahostsv4 "$1" 2>/dev/null | awk '/STREAM/ {print $1; exit}'
}
HOST_IP="$(resolve_ip "$KRB_HOST" || true)"
echo "  $KRB_HOST → ${HOST_IP:-<unresolved>}"
if [[ -z "$HOST_IP" ]]; then
  echo "FAIL: cannot resolve $KRB_HOST"
  exit 1
fi
if [[ "$HOST_IP" != "127.0.0.1" && "$HOST_IP" != "::1" ]]; then
  # Lab kudu binds 127.0.0.1 only; MagicDNS often returns an unreachable IP.
  if ! timeout 1 bash -c "echo >/dev/tcp/${HOST_IP}/7051" 2>/dev/null; then
    echo "WARN: $KRB_HOST → $HOST_IP:7051 not reachable; Kudu is typically on 127.0.0.1:7051."
    echo "      Add a hosts override (files before DNS) so SPN host maps to loopback:"
    echo "        echo '127.0.0.1 $KRB_HOST' | sudo tee -a /etc/hosts"
    if sudo -n true 2>/dev/null; then
      if ! grep -qE "^[[:space:]]*127\\.0\\.0\\.1[[:space:]].*${KRB_HOST}" /etc/hosts 2>/dev/null; then
        echo "      Attempting to add hosts entry (sudo -n)..."
        echo "127.0.0.1 ${KRB_HOST}" | sudo tee -a /etc/hosts >/dev/null
      fi
      HOST_IP="$(resolve_ip "$KRB_HOST" || true)"
      echo "  re-resolved $KRB_HOST → ${HOST_IP:-<unresolved>}"
    fi
  fi
fi
if ! timeout 1 bash -c "echo >/dev/tcp/${KRB_HOST}/7051" 2>/dev/null; then
  echo "FAIL: cannot TCP-connect to ${KRB_HOST}:7051 (need hosts → 127.0.0.1 while Kudu binds loopback)"
  exit 1
fi
echo "  TCP ${KRB_HOST}:7051 OK"

# Shell kinit is optional when USER MAPPING keytab is set (backend kinit in K5b).
# Still do it so klist in this script is informative.
kinit -kt "$USER_KEYTAB" "$PRINCIPAL"
klist | head -6

psql -h 127.0.0.1 -p 5455 -d signals -v ON_ERROR_STOP=1 <<SQL
-- Kerberos product path: masters host MUST match kudu/ SPN (not 127.0.0.1).
ALTER SERVER impala_kudu_srv OPTIONS (
  SET auth 'kerberos',
  SET kudu_masters '${MASTERS}'
);

-- USER MAPPING: explicit principal + keytab (K5b kinit in backend before Build)
DROP USER MAPPING IF EXISTS FOR CURRENT_USER SERVER impala_kudu_srv;
CREATE USER MAPPING FOR CURRENT_USER
  SERVER impala_kudu_srv
  OPTIONS (
    principal '${PRINCIPAL}',
    keytab '${USER_KEYTAB}'
  );

SET impala_fdw.enable_kudu_scan = on;
SET impala_fdw.log_path_choice = on;

EXPLAIN (VERBOSE, COSTS OFF)
SELECT type_name, name FROM atlas_entity_flat LIMIT 3;

ALTER FOREIGN TABLE atlas_entity_flat OPTIONS (SET access 'kudu_scan');
SELECT type_name, name FROM atlas_entity_flat LIMIT 3;
ALTER FOREIGN TABLE atlas_entity_flat OPTIONS (SET access 'auto');
SQL

echo "K5c FDW smoke: forced kudu_scan as ${PRINCIPAL} via masters ${MASTERS} completed."
