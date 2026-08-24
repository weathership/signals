#!/usr/bin/env bash
# Impala buildall under devenv isolation (project Maven + toolchain thrift/boost).
# Prefer: devenv tasks run impala:build
set -eo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export SIG_MAVEN_REPO="${SIG_MAVEN_REPO:-$ROOT/.devenv/m2}"
mkdir -p "$SIG_MAVEN_REPO"
export MAVEN_ARGS="${MAVEN_ARGS:-} -Dmaven.repo.local=$SIG_MAVEN_REPO"

# Drop thrift/boost pollution (keep sasl/krb5/openssl).
for _v in PATH CMAKE_INCLUDE_PATH CMAKE_LIBRARY_PATH CMAKE_PREFIX_PATH \
          PKG_CONFIG_PATH LIBRARY_PATH CPATH CPLUS_INCLUDE_PATH; do
  _cur="${!_v:-}"
  [ -z "$_cur" ] && continue
  _filtered="$(printf '%s' "$_cur" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
  export "$_v=$_filtered"
done

# Portable krb5/gssapi/sasl/ssl discovery (devenv sets SIG_* when available).
# Isolated builds do not load devenv.nix enterShell — recover cyrus_sasl -dev.
if [ -z "${SIG_SASL_INC:-}" ]; then
  # Prefer the split cyrus-sasl -dev store path. The devenv profile include/
  # also contains protobuf headers that pull absl and break Impala's toolchain
  # protoc-gen-insertions.
  _sasl_h="$(ls -1 /nix/store/*cyrus-sasl*-dev/include/sasl/sasl.h 2>/dev/null | head -1 || true)"
  if [ -n "$_sasl_h" ] && [ -f "$_sasl_h" ]; then
    export SIG_SASL_INC="$(cd "$(dirname "$_sasl_h")/.." && pwd)"
  elif [ -f /usr/include/sasl/sasl.h ]; then
    export SIG_SASL_INC=/usr/include
  fi
  unset _sasl_h
fi
if [ -z "${SIG_SASL_LIB:-}" ]; then
  _sasl_so="$(ls -1 /nix/store/*cyrus-sasl*/lib/libsasl2.so 2>/dev/null | grep -v -- '-dev/' | head -1 || true)"
  if [ -n "$_sasl_so" ] && [ -e "$_sasl_so" ]; then
    export SIG_SASL_LIB="$(cd "$(dirname "$_sasl_so")" && pwd)"
  fi
  unset _sasl_so
fi
# shellcheck source=/dev/null
. "$ROOT/config/asf/native-link-env.sh"
echo "SIG_SASL_INC=${SIG_SASL_INC:-} SIG_SASL_LIB=${SIG_SASL_LIB:-}"

cp -f config/impala/impala-config-local.sh components/impala/bin/impala-config-local.sh
cd components/impala
# shellcheck source=/dev/null
source bin/impala-config.sh

# impala-config.sh defaults JAVA_HOME to JDK 11. iceberg-hdf5/jhdf are Java 17+.
# Match devenv impala:build (jdk21_headless).
if [ -x "${ROOT}/.devenv/profile/bin/java" ]; then
  export JAVA_HOME="${ROOT}/.devenv/profile"
  export PATH="$JAVA_HOME/bin:$PATH"
  export JAVA="$JAVA_HOME/bin/java"
  echo "Re-assert JAVA_HOME=$JAVA_HOME after impala-config.sh"
  java -version 2>&1 | head -1
fi

# Toolchain gcc before Nix gcc (gutil breaks under GCC 15 / C++20 -Werror)
if [ -n "${IMPALA_TOOLCHAIN_PACKAGES_HOME:-}" ] && \
   [ -x "$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/bin/g++" ]; then
  export PATH="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/bin:$PATH"
  export CC="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/bin/gcc"
  export CXX="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/bin/g++"
fi
if [ -n "${THRIFT_CPP_HOME:-}" ] && [ -d "$THRIFT_CPP_HOME/bin" ]; then
  export PATH="$THRIFT_CPP_HOME/bin:$PATH"
fi

if ! ls "$SIG_MAVEN_REPO"/org/apache/ranger/ranger-plugins-common/"$IMPALA_RANGER_VERSION"/*.jar >/dev/null 2>&1; then
  echo "Ranger jars missing in $SIG_MAVEN_REPO for version $IMPALA_RANGER_VERSION."
  echo "Run: devenv tasks run ranger:build"
  exit 1
fi

if [ -f CMakeCache.txt ] && grep -qE '/nix/store/[^ ]*thrift|/nix/store/[^ ]*boost' CMakeCache.txt; then
  echo "WARNING: CMakeCache references Nix thrift/boost — removing cache"
  rm -f CMakeCache.txt
  rm -rf CMakeFiles
fi
# Bare -lgssapi_krb5 cannot link under Nix gold; force reconfigure for full-path target
if [ -f be/src/service/CMakeFiles/impalad.dir/link.txt ] && \
   grep -qE '(^|[^-])-lgssapi_krb5' be/src/service/CMakeFiles/impalad.dir/link.txt 2>/dev/null; then
  echo "WARNING: bare -lgssapi_krb5 in link line — reconfigure cmake"
  rm -f CMakeCache.txt
  rm -rf CMakeFiles
fi

echo "THRIFT_CPP_HOME=$THRIFT_CPP_HOME"
echo "thrift=$(command -v thrift || echo none)"
echo "SIG_KRB5_LIB=${SIG_KRB5_LIB:-}"
echo "SIG_MAVEN_REPO=$SIG_MAVEN_REPO"
echo "IMPALA_RANGER_VERSION=$IMPALA_RANGER_VERSION"
echo "RANGER_HOME=$RANGER_HOME"
echo "Starting buildall.sh -notests -noclean ..."
./buildall.sh -notests -noclean
echo IMPALA_BUILD_OK
