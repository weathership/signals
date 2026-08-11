# shellcheck shell=bash
# Shared Kerberos env for Signals — required, no NOSASL fallback.
#
# Principals (realm DEV.VISTA.ZNDX.ORG by default):
#   signals@REALM                         — user (signals.keytab)
#   impala/$SIGNALS_KRB_HOST@REALM        — Impala daemons
#   kudu/$SIGNALS_KRB_HOST@REALM          — Kudu
#   postgres/$SIGNALS_KRB_HOST@REALM      — optional PG GSSAPI
#
# Clients MUST dial $SIGNALS_KRB_HOST (not 127.0.0.1) so the SPN matches keytabs.

signals_krb_env() {
  local root="${1:-${DEVENV_ROOT:-$PWD}}"
  export SIGNALS_KRB_HOST="${SIGNALS_KRB_HOST:-tinybox.dev.vista.zndx.org}"
  export KRB5_REALM="${KRB5_REALM:-DEV.VISTA.ZNDX.ORG}"
  export KDC_DIR="${KDC_DIR:-$root/.devenv/kdc}"
  export KRB5_CONFIG="${KRB5_CONFIG:-$KDC_DIR/krb5.conf}"
  export KRB5_KDC_PROFILE="${KRB5_KDC_PROFILE:-$KDC_DIR/kdc.conf}"
  export KRB5CCNAME="${KRB5CCNAME:-$KDC_DIR/krb5cc}"
  export SIGNALS_KRB_USER_KEYTAB="${SIGNALS_KRB_USER_KEYTAB:-$KDC_DIR/signals.keytab}"
  export SIGNALS_IMPALA_KEYTAB="${SIGNALS_IMPALA_KEYTAB:-$KDC_DIR/impala.keytab}"
  export SIGNALS_KUDU_KEYTAB="${SIGNALS_KUDU_KEYTAB:-$KDC_DIR/kudu.keytab}"
  # HS2 / advertise host for SPN (never 127.0.0.1 for GSSAPI)
  export IMPALA_HS2_HOST="${IMPALA_HS2_HOST:-$SIGNALS_KRB_HOST}"
  export IMPALA_HS2_PORT="${IMPALA_HS2_PORT:-21050}"
  export SIGNALS_USER_PRINCIPAL="${SIGNALS_USER_PRINCIPAL:-signals@$KRB5_REALM}"
  export SIGNALS_IMPALA_PRINCIPAL="${SIGNALS_IMPALA_PRINCIPAL:-impala/$SIGNALS_KRB_HOST@$KRB5_REALM}"
}

signals_krb_hosts_ok() {
  signals_krb_env "${1:-}"
  getent hosts "$SIGNALS_KRB_HOST" >/dev/null 2>&1
}

signals_krb_require_layout() {
  signals_krb_env "${1:-}"
  local missing=0
  if [ ! -f "$KRB5_CONFIG" ]; then
    echo "ERROR: $KRB5_CONFIG missing" >&2
    missing=1
  fi
  for kt in "$SIGNALS_KRB_USER_KEYTAB" "$SIGNALS_IMPALA_KEYTAB" "$SIGNALS_KUDU_KEYTAB"; do
    if [ ! -f "$kt" ]; then
      echo "ERROR: keytab missing: $kt" >&2
      missing=1
    fi
  done
  if ! signals_krb_hosts_ok; then
    echo "ERROR: $SIGNALS_KRB_HOST does not resolve" >&2
    echo "  Fix: echo '127.0.0.1 $SIGNALS_KRB_HOST' | sudo tee -a /etc/hosts" >&2
    missing=1
  fi
  if [ "$missing" -ne 0 ]; then
    echo "  Fix: devenv up -d (signals:kerberos-bootstrap) or just bootstrap" >&2
    return 1
  fi
  return 0
}

signals_krb_kinit() {
  signals_krb_env "${1:-}"
  signals_krb_require_layout "$1" || return 1
  if ! command -v kinit >/dev/null 2>&1; then
    echo "ERROR: kinit not on PATH" >&2
    return 1
  fi
  kinit -kt "$SIGNALS_KRB_USER_KEYTAB" "$SIGNALS_USER_PRINCIPAL" || {
    echo "ERROR: kinit failed for $SIGNALS_USER_PRINCIPAL" >&2
    return 1
  }
  echo "kinit ok: $SIGNALS_USER_PRINCIPAL (KRB5CCNAME=$KRB5CCNAME)"
  klist 2>/dev/null | head -8 || true
}

signals_krb_ticket_ok() {
  signals_krb_env "${1:-}"
  klist -s 2>/dev/null
}

# Full bootstrap: KDC layout + ticket (required before devenv up / just backup)
signals_krb_bootstrap() {
  local root="${1:-${DEVENV_ROOT:-$PWD}}"
  signals_krb_env "$root"
  if [ ! -f "$KRB5_CONFIG" ] || [ ! -f "$SIGNALS_KRB_USER_KEYTAB" ]; then
    echo "→ initializing KDC (signals:kdc-init)"
    (cd "$root" && devenv tasks run signals:kdc-init) || return 1
  fi
  signals_krb_require_layout "$root" || return 1
  signals_krb_kinit "$root" || return 1
  # Persist required client env (no auth toggles — Kerberos is the only path)
  local env_file="$root/.env"
  touch "$env_file"
  _set_env() {
    local k="$1" v="$2"
    if grep -q "^${k}=" "$env_file" 2>/dev/null; then
      sed -i "s|^${k}=.*|${k}=${v}|" "$env_file"
    else
      echo "${k}=${v}" >> "$env_file"
    fi
  }
  _set_env SIGNALS_KRB_HOST "$SIGNALS_KRB_HOST"
  _set_env IMPALA_HS2_HOST "$SIGNALS_KRB_HOST"
  _set_env SIGNALS_KRB_USER_KEYTAB ".devenv/kdc/signals.keytab"
  echo "✓ Kerberos bootstrap complete (realm=$KRB5_REALM host=$SIGNALS_KRB_HOST)"
}
