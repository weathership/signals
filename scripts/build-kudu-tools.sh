#!/usr/bin/env bash
# Build the C++ Kudu client tools into .devenv/bin/.
# Guru: #SL.00000027.SCHEMA2
#
# These were previously compiled ad hoc, which is why .devenv/bin/ came back
# empty after a clean and why the creator had to be rebuilt by hand. Run from
# a devenv shell (pkg-config resolves the Nix cyrus-sasl that libkudu_client's
# @SASL2 versioned symbols need).
#
#   devenv shell -- scripts/build-kudu-tools.sh [tool ...]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

KUDU_VER="${IMPALA_KUDU_VERSION:-879a8f9e2}"
TC="${IMPALA_TOOLCHAIN_PACKAGES_HOME:-$ROOT/components/impala/toolchain/toolchain-packages-gcc10.4.0}"
INC="$TC/kudu-$KUDU_VER/release/include"
LIB="$ROOT/.devenv/impala/lib"
OUT="$ROOT/.devenv/bin"

[ -f "$INC/kudu/client/client.h" ] || {
  echo "ERROR: Kudu headers not found: $INC" >&2
  echo "  Set IMPALA_TOOLCHAIN_PACKAGES_HOME or IMPALA_KUDU_VERSION." >&2
  exit 1
}
[ -f "$LIB/libkudu_client.so" ] || {
  echo "ERROR: libkudu_client.so not found: $LIB" >&2
  echo "  Expected the devenv Impala symlink farm. Guru: #SL.00000027.SCHEMA2" >&2
  exit 1
}

SASL_LIBS="$(pkg-config --libs libsasl2 2>/dev/null || echo -lsasl2)"

# libkudu_client references sasl_*@SASL2, versioned against the Impala
# toolchain's libsasl2. The devenv farm ships only libsasl2.so.2 (no
# unversioned .so), so -lsasl2 cannot satisfy them at link time. They resolve
# at load time against Nix libsasl2.so.3 -- impala_fdw.so runs the same way,
# reporting "no version information available" and working. Let the linker
# defer them rather than pinning a toolchain lib the runtime will not use.
LINK_EXTRA="-Wl,--allow-shlib-undefined"

TOOLS=("$@")
if [ ${#TOOLS[@]} -eq 0 ]; then
  TOOLS=(signals_kudu_create gpu_kudu_create gpu_kudu_ingest)
fi

mkdir -p "$OUT"
for t in "${TOOLS[@]}"; do
  src="scripts/$t.cc"
  [ -f "$src" ] || { echo "skip $t (no $src)"; continue; }
  echo "building $t"
  # shellcheck disable=SC2086
  g++ -std=c++17 -O2 -Wall -o "$OUT/$t" "$src" \
    -I"$INC" -L"$LIB" -lkudu_client $SASL_LIBS -lkrb5 -lgssapi_krb5 \
    $LINK_EXTRA -Wl,-rpath,"$LIB"
  file "$OUT/$t" | grep -q ELF || { echo "ERROR: $t did not link"; exit 1; }
done

ls -la "$OUT"
