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

cp -f config/impala/impala-config-local.sh components/impala/bin/impala-config-local.sh
cd components/impala
# shellcheck source=/dev/null
source bin/impala-config.sh

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

echo "THRIFT_CPP_HOME=$THRIFT_CPP_HOME"
echo "thrift=$(command -v thrift || echo none)"
echo "SIG_MAVEN_REPO=$SIG_MAVEN_REPO"
echo "IMPALA_RANGER_VERSION=$IMPALA_RANGER_VERSION"
echo "RANGER_HOME=$RANGER_HOME"
echo "Starting buildall.sh -notests -noclean ..."
./buildall.sh -notests -noclean
echo IMPALA_BUILD_OK
