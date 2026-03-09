#!/usr/bin/env bash
# Idempotent KDC initialization for local development.
# Modeled on Apache Kudu's MiniKdc patterns.
#
# Creates a project-local MIT Kerberos KDC with:
#   Realm:  KRBTEST.COM
#   Port:   8848
#   Data:   .devenv/kdc/
#
# Usage: scripts/kdc-init.sh [--reset]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

KDC_DIR="$PROJECT_DIR/.devenv/kdc"
REALM="${KRB5_REALM:-KRBTEST.COM}"
KDC_PORT="${KRB5_KDC_PORT:-8848}"
MASTER_PW="masterpw"

# Handle --reset flag
if [[ "${1:-}" == "--reset" ]]; then
    echo "Resetting KDC database..."
    rm -rf "$KDC_DIR"
fi

mkdir -p "$KDC_DIR"

# ── Write krb5.conf ──────────────────────────────────────────────────────────
cat > "$KDC_DIR/krb5.conf" <<EOF
[logging]
    kdc = FILE:/dev/stderr

[libdefaults]
    default_realm = $REALM
    dns_lookup_kdc = false
    dns_lookup_realm = false
    forwardable = true
    renew_lifetime = 7d
    ticket_lifetime = 24h
    rdns = false
    ignore_acceptor_hostname = true
    default_tkt_enctypes = aes256-cts aes128-cts
    default_tgs_enctypes = aes256-cts aes128-cts
    permitted_enctypes = aes256-cts aes128-cts

[realms]
    $REALM = {
        kdc = 127.0.0.1:$KDC_PORT
    }
EOF

# ── Write kdc.conf ───────────────────────────────────────────────────────────
cat > "$KDC_DIR/kdc.conf" <<EOF
[kdcdefaults]
    kdc_ports = $KDC_PORT
    kdc_tcp_ports = ""

[realms]
    $REALM = {
        acl_file = $KDC_DIR/kadm5.acl
        admin_keytab = $KDC_DIR/kadm5.keytab
        database_name = $KDC_DIR/principal
        key_stash_file = $KDC_DIR/.k5.$REALM
        max_renewable_life = 7d 0h 0m 0s
    }
EOF

# ── Write kadm5.acl ─────────────────────────────────────────────────────────
cat > "$KDC_DIR/kadm5.acl" <<EOF
*/admin@$REALM *
EOF

# ── Initialize KDC database (idempotent) ─────────────────────────────────────
if [[ ! -f "$KDC_DIR/principal" ]]; then
    echo "Initializing KDC database for realm $REALM..."
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kdb5_util create -s -P "$MASTER_PW" -W -r "$REALM"

    echo "Creating principals..."

    # Service principal for PostgreSQL GSSAPI authentication
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kadmin.local -r "$REALM" -q "add_principal -randkey postgres/localhost@$REALM"

    # Export keytab for PostgreSQL
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kadmin.local -r "$REALM" -q "ktadd -k $KDC_DIR/postgres.keytab postgres/localhost@$REALM"

    # Application user principal (password = username)
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kadmin.local -r "$REALM" -q "add_principal -pw signals signals@$REALM"

    echo "KDC initialized successfully."
    echo "  Realm:    $REALM"
    echo "  Port:     $KDC_PORT"
    echo "  Data:     $KDC_DIR"
    echo "  Keytab:   $KDC_DIR/postgres.keytab"
else
    echo "KDC database already exists at $KDC_DIR (use --reset to recreate)."
fi
