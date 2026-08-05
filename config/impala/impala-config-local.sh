# signals-360 — local Impala overrides (copied to components/impala/bin/ by devenv tasks).
# Impala sources this file from bin/impala-config-local.sh (gitignored in the submodule).
#
# Prefer in-tree ASF components over CDP-bundled Ranger (and friends) where we build them.

# --- Ranger (components/ranger → .devenv/ranger/admin) ----------------------------
# Non-empty RANGER_VERSION_OVERRIDE:
#   1) skips CDP/Apache ranger-admin tarball download in bootstrap_toolchain.py
#   2) sets IMPALA_RANGER_VERSION for FE Maven (ranger-plugins-*)
# Install local jars into the *project* Maven repo (not ~/.m2):
#   devenv tasks run ranger:build   # → $PWD/.devenv/m2
# Impala FE tasks set MAVEN_ARGS=-Dmaven.repo.local=$SIG_MAVEN_REPO
export RANGER_VERSION_OVERRIDE="${RANGER_VERSION_OVERRIDE:-3.0.0-SNAPSHOT}"

# Runtime / minicluster admin tree (setup.sh layout). Materialized by ranger:install.
_signals_root="$(cd "${IMPALA_HOME}/../.." && pwd)"
export RANGER_HOME_OVERRIDE="${RANGER_HOME_OVERRIDE:-${_signals_root}/.devenv/ranger/admin}"

# --- Kudu (optional local C++ build) ---------------------------------------------
# When components/kudu is built, prefer it for native linkage notes / tooling.
# Impala's Java still uses toolchain Kudu artifacts unless IMPALA_KUDU_* is fully
# re-pointed; leave toolchain Kudu for FE unless SIG_USE_LOCAL_KUDU=1.
if [ "${SIG_USE_LOCAL_KUDU:-0}" = "1" ]; then
  _kudu_latest="${_signals_root}/components/kudu/build/latest"
  if [ -x "${_kudu_latest}/bin/kudu-master" ]; then
    export KUDU_BUILD="${KUDU_BUILD:-${_kudu_latest}}"
    echo "signals: SIG_USE_LOCAL_KUDU=1 → KUDU_BUILD=${KUDU_BUILD}"
  fi
fi

echo "signals impala-config-local: RANGER_VERSION_OVERRIDE=${RANGER_VERSION_OVERRIDE}"
echo "signals impala-config-local: RANGER_HOME_OVERRIDE=${RANGER_HOME_OVERRIDE}"
