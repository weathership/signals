#!/usr/bin/env bash
# PR-K5c: forced kudu_scan as signals@REALM against Kerberos-required Kudu.
#
# Prerequisites:
#   SIGNALS_KUDU_KERBEROS=1 and kudu-master/tserver restarted with
#     --principal=kudu/$SIGNALS_KRB_HOST (not kudu/_HOST → uname)
#   impala_fdw built with K5b/K5c (SASL + EXPLAIN Principal)
#   Atlas FTs present (config/atlas/kudu_projections_fdw.sql)
#
# Usage:
#   SIGNALS_KUDU_KERBEROS=1 bash scripts/kudu_kerberos_fdw_smoke.sh
#
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KDC_DIR="${KDC_DIR:-$PROJECT_DIR/.devenv/kdc}"
REALM="${KRB5_REALM:-DEV.VISTA.ZNDX.ORG}"
USER_KEYTAB="${SIGNALS_KRB_USER_KEYTAB:-$KDC_DIR/signals.keytab}"
export KRB5_CONFIG="${KRB5_CONFIG:-$KDC_DIR/krb5.conf}"
export KRB5CCNAME="${KRB5CCNAME:-$KDC_DIR/krb5cc_k5c_fdw}"
export SIGNALS_KRB_USER_KEYTAB="$USER_KEYTAB"

MODE="${SIGNALS_KUDU_KERBEROS:-0}"
if [[ "$MODE" != "1" ]]; then
  echo "WARN: SIGNALS_KUDU_KERBEROS=$MODE — set to 1 and restart Kudu for required auth."
fi

echo "=== K5c FDW Kerberos smoke ==="
echo "  KRB5CCNAME=$KRB5CCNAME"
kinit -kt "$USER_KEYTAB" "signals@$REALM"
klist | head -6

psql -h 127.0.0.1 -p 5455 -d signals -v ON_ERROR_STOP=1 <<SQL
ALTER SERVER impala_kudu_srv OPTIONS (SET auth 'kerberos');
-- map current OS/pg user; principal override for signals identity
DO \$\$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_user_mappings um
    JOIN pg_foreign_server fs ON fs.oid = um.srvid
    WHERE fs.srvname = 'impala_kudu_srv' AND um.usename = current_user
  ) THEN
    EXECUTE format(
      'CREATE USER MAPPING FOR %I SERVER impala_kudu_srv OPTIONS (principal %L, keytab %L)',
      current_user, 'signals@$REALM', '$USER_KEYTAB');
  ELSE
    -- best-effort update
    BEGIN
      EXECUTE format(
        'ALTER USER MAPPING FOR %I SERVER impala_kudu_srv OPTIONS (SET principal %L, SET keytab %L)',
        current_user, 'signals@$REALM', '$USER_KEYTAB');
    EXCEPTION WHEN OTHERS THEN
      NULL;
    END;
  END IF;
END\$\$;

SET impala_fdw.enable_kudu_scan = on;
SET impala_fdw.log_path_choice = on;

EXPLAIN (VERBOSE, COSTS OFF)
SELECT type_name, name FROM atlas_entity_flat LIMIT 3;

ALTER FOREIGN TABLE atlas_entity_flat OPTIONS (SET access 'kudu_scan');
SELECT type_name, name FROM atlas_entity_flat LIMIT 3;
ALTER FOREIGN TABLE atlas_entity_flat OPTIONS (SET access 'auto');

-- restore lab nosasl after smoke (optional; comment out for full MODE=1 lab)
-- ALTER SERVER impala_kudu_srv OPTIONS (SET auth 'nosasl');
SQL

echo "K5c FDW smoke: forced kudu_scan as signals@$REALM completed."
