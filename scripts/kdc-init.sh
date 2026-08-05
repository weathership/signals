#!/usr/bin/env bash
# Idempotent KDC initialization for local development.
#
# Creates a project-local MIT Kerberos KDC with ZNDX-realistic naming:
#   Realm:  DEV.VISTA.ZNDX.ORG     ({ENV}.{LOCATION}.ZNDX.ORG)
#   Host:   tinybox.dev.vista.zndx.org  (host.posture.location.tld)
#   Port:   8848 (127.0.0.1 only — not public DNS)
#   Data:   .devenv/kdc/
#
# PG role mapping (impala_fdw / GSSAPI):
#   signals@DEV.VISTA.ZNDX.ORG  →  PostgreSQL role "signals"
#   (realm includes env segment; PG role is short primary only)
#
# DNS/Cloudflare FQDN is used for SPN instances; the KDC itself stays on
# loopback. Add to /etc/hosts if needed:
#   127.0.0.1 tinybox.dev.vista.zndx.org
#
# Usage: scripts/kdc-init.sh [--reset]
#
# Env overrides:
#   KRB5_REALM             default from SIGNALS_KRB_ENV + SIGNALS_KRB_LOCATION
#   SIGNALS_KRB_ENV        default dev  → realm segment DEV
#   SIGNALS_KRB_LOCATION   default vista → realm segment VISTA
#   SIGNALS_KRB_HOST       default tinybox.dev.vista.zndx.org
#   KRB5_KDC_PORT          default 8848

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

KDC_DIR="$PROJECT_DIR/.devenv/kdc"

# Env / location segments → realm {ENV}.{LOCATION}.ZNDX.ORG
KRB_ENV_RAW="${SIGNALS_KRB_ENV:-dev}"
KRB_LOC_RAW="${SIGNALS_KRB_LOCATION:-vista}"
KRB_ENV_UP="$(echo "$KRB_ENV_RAW" | tr '[:lower:]' '[:upper:]')"
KRB_LOC_UP="$(echo "$KRB_LOC_RAW" | tr '[:lower:]' '[:upper:]')"
DEFAULT_REALM="${KRB_ENV_UP}.${KRB_LOC_UP}.ZNDX.ORG"

REALM="${KRB5_REALM:-$DEFAULT_REALM}"
KRB_HOST="${SIGNALS_KRB_HOST:-tinybox.${KRB_ENV_RAW}.${KRB_LOC_RAW}.zndx.org}"
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
    # Prefer correct FQDN SPNs; keep as escape hatch for local loopback clients.
    ignore_acceptor_hostname = true
    default_tkt_enctypes = aes256-cts aes128-cts
    default_tgs_enctypes = aes256-cts aes128-cts
    permitted_enctypes = aes256-cts aes128-cts

[realms]
    $REALM = {
        kdc = 127.0.0.1:$KDC_PORT
    }

[domain_realm]
    .${KRB_LOC_RAW}.zndx.org = $REALM
    ${KRB_LOC_RAW}.zndx.org = $REALM
    .${KRB_ENV_RAW}.${KRB_LOC_RAW}.zndx.org = $REALM
    $KRB_HOST = $REALM
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

# ── pg_ident-style map (for docs / future PG conf generation) ────────────────
# principal primary @ REALM  →  PG role = primary (env lives in realm only)
cat > "$KDC_DIR/pg_ident.map.example" <<EOF
# Map Kerberos principals to short PostgreSQL roles.
# signals@DEV.VISTA.ZNDX.ORG → role "signals"
# (realm includes env segment; role does not)
krb_map  /^(.*)@${REALM//./\\.}\$  \\1
EOF

# Helper: add principal + optional keytab (idempotent via kadmin errors ignored for exists)
add_service_principal() {
    local spn="$1"
    local keytab="${2:-}"
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kadmin.local -r "$REALM" -q "add_principal -randkey $spn@$REALM" 2>/dev/null || true
    if [[ -n "$keytab" ]]; then
        KRB5_CONFIG="$KDC_DIR/krb5.conf" \
        KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
            kadmin.local -r "$REALM" -q "ktadd -k $keytab $spn@$REALM"
    fi
}

# ── Initialize KDC database (idempotent) ─────────────────────────────────────
if [[ ! -f "$KDC_DIR/principal" ]]; then
    echo "Initializing KDC database for realm $REALM (host $KRB_HOST)..."
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kdb5_util create -s -P "$MASTER_PW" -W -r "$REALM"

    echo "Creating principals..."

    # PostgreSQL GSSAPI service
    add_service_principal "postgres/$KRB_HOST" "$KDC_DIR/postgres.keytab"

    # Impala (when auth enabled)
    add_service_principal "impala/$KRB_HOST" "$KDC_DIR/impala.keytab"

    # HTTP for Atlas / Ranger SPNEGO
    add_service_principal "HTTP/$KRB_HOST" "$KDC_DIR/http.keytab"

    # Kudu (when Kerberosized)
    add_service_principal "kudu/$KRB_HOST" "$KDC_DIR/kudu.keytab"

    # Application user principal (password = username for local dev)
    # PG role mapping: signals@DEV.VISTA.ZNDX.ORG → role "signals"
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kadmin.local -r "$REALM" -q "add_principal -pw signals signals@$REALM"

    # User keytab for headless FDW / secretspec (SIGNALS_KRB_USER_KEYTAB)
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kadmin.local -r "$REALM" -q "ktadd -k $KDC_DIR/signals.keytab signals@$REALM"

    # Optional admin principal for kadmind ACL experiments
    KRB5_CONFIG="$KDC_DIR/krb5.conf" \
    KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        kadmin.local -r "$REALM" -q "add_principal -pw signals signals/admin@$REALM" 2>/dev/null || true

    echo "KDC initialized successfully."
    echo "  Realm:    $REALM  (env=$KRB_ENV_UP location=$KRB_LOC_UP)"
    echo "  Host:     $KRB_HOST"
    echo "  Port:     $KDC_PORT (127.0.0.1)"
    echo "  Data:     $KDC_DIR"
    echo "  Keytabs:  $KDC_DIR/{postgres,impala,http,kudu,signals}.keytab"
    echo "  User:     signals@$REALM (password: signals; also signals.keytab)"
    echo "  PG role:  signals  ←  signals@$REALM  (see pg_ident.map.example)"
    echo "  SecretSpec: optional SIGNALS_KRB_USER_KEYTAB=$KDC_DIR/signals.keytab in .env"
    echo "  Hint:     echo '127.0.0.1 $KRB_HOST' | sudo tee -a /etc/hosts"
else
    echo "KDC database already exists at $KDC_DIR (use --reset to recreate)."
    echo "  Expected realm: $REALM  host: $KRB_HOST"
    echo "  If upgrading realm (e.g. VISTA.ZNDX.ORG → DEV.VISTA.ZNDX.ORG), run: devenv tasks run signals:kdc-reset"
fi
