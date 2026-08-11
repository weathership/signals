#!/usr/bin/env bash
# One-time binary + keytab gate before Kudu/Impala processes on `devenv up`.
# Does NOT compile ASF trees (too long for up -d) — fails with the build tasks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { echo "data-plane-preflight: $*"; }
die() { echo "ERROR: data-plane-preflight: $*" >&2; exit 1; }

KUDU_BUILD="${KUDU_BUILD:-$ROOT/components/kudu/build/latest}"
IMPALA_HOME="${IMPALA_HOME:-$ROOT/components/impala}"
KDC_DIR="${KDC_DIR:-$ROOT/.devenv/kdc}"

missing=0
need_build=0

req_file() {
  local p="$1" hint="${2:-}"
  if [[ ! -f "$p" && ! -x "$p" ]]; then
    info "MISSING: $p${hint:+ — $hint}"
    missing=1
    return 1
  fi
  return 0
}

info "checking Kudu binaries under $KUDU_BUILD"
if ! req_file "$KUDU_BUILD/bin/kudu-master" "devenv tasks run kudu:build-cpp"; then need_build=1; fi
if ! req_file "$KUDU_BUILD/bin/kudu-tserver" "devenv tasks run kudu:build-cpp"; then need_build=1; fi

if [[ "$(uname -s)" == "Linux" ]]; then
  info "checking Impala binaries under $IMPALA_HOME/be/build/latest"
  for b in statestored catalogd impalad; do
    if ! req_file "$IMPALA_HOME/be/build/latest/service/$b" "devenv tasks run impala:build"; then
      need_build=1
    fi
  done
  if [[ ! -s "$IMPALA_HOME/java/impala-package/target/package-classpath.txt" ]]; then
    info "MISSING: Impala FE package-classpath.txt — devenv tasks run impala:build-fe"
    missing=1
    need_build=1
  fi
else
  info "Darwin: skipping Impala binary checks (processes are Linux-only)"
fi

info "checking Kerberos keytabs under $KDC_DIR"
# shellcheck source=/dev/null
. "$ROOT/scripts/signals_kerberos.sh"
signals_krb_env "$ROOT"
for kt in "$SIGNALS_KRB_USER_KEYTAB" "$SIGNALS_IMPALA_KEYTAB" "$SIGNALS_KUDU_KEYTAB"; do
  if [[ ! -f "$kt" ]]; then
    info "MISSING keytab: $kt (will be created by signals:kerberos-bootstrap after KDC is up)"
    # Not fatal here if bootstrap task runs next — only warn
  fi
done

# shellcheck source=/dev/null
. "$ROOT/scripts/signals_data_root.sh"
signals_ensure_data_layout
info "data layout OK under ${SIGNALS_DATA_ROOT:-?}"

if [[ "$need_build" -eq 1 ]]; then
  cat >&2 <<EOF
ERROR: data-plane-preflight: ASF data-plane binaries missing (one-time build).

  devenv tasks run kudu:build-cpp
  devenv tasks run impala:bootstrap   # toolchain if needed
  devenv tasks run impala:build       # or impala:build-fe if only FE missing

Then re-run: devenv up -d
EOF
  exit 1
fi

if [[ "$missing" -ne 0 ]]; then
  die "required files missing"
fi

info "OK — Kudu/Impala binaries present; data layout ready"
exit 0
