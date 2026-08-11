#!/usr/bin/env bash
# Post-up smoke for Kudu + Impala (lab). Invoked from stack-ready when enabled.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { echo "data-plane-smoke: $*"; }
die() { echo "ERROR: data-plane-smoke: $*" >&2; exit 1; }

tcp_ok() {
  timeout 2 bash -c "echo >/dev/tcp/${1}/${2}" 2>/dev/null
}

http_ok() {
  curl -sf -m 3 "$1" >/dev/null 2>&1
}

info "=== Kudu ==="
http_ok "http://127.0.0.1:8051/" || die "kudu-master web :8051 not up"
ok_master=1
http_ok "http://127.0.0.1:8050/" || die "kudu-tserver web :8050 not up"
info "OK  kudu-master :8051  kudu-tserver :8050"

if [[ "$(uname -s)" != "Linux" ]]; then
  info "Darwin: skip Impala smoke"
  exit 0
fi

info "=== Impala ==="
http_ok "http://127.0.0.1:25010/" || die "impala-statestore web :25010 not up"
http_ok "http://127.0.0.1:25020/" || die "impala-catalogd web :25020 not up"
http_ok "http://127.0.0.1:25000/" || die "impalad web :25000 not up"
tcp_ok 127.0.0.1 21050 || die "Impala HS2 :21050 not accepting TCP"
info "OK  statestore :25010  catalogd :25020  impalad web :25000  HS2 :21050"

# Optional GSSAPI probe when keytab layout present
# shellcheck source=/dev/null
. "$ROOT/scripts/signals_kerberos.sh"
signals_krb_env "$ROOT"
if [[ -f "${SIGNALS_KRB_USER_KEYTAB:-}" ]] && command -v kinit >/dev/null 2>&1; then
  if signals_krb_kinit "$ROOT" >/dev/null 2>&1; then
    info "OK  user ticket (kinit)"
  else
    info "WARN kinit failed — HS2 GSSAPI may fail (check keytabs)"
  fi
fi

info "data-plane smoke OK"
exit 0
