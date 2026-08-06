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
# Resolve signals repo root without depending on a pre-set IMPALA_HOME (devenv-safe).
if [ -n "${IMPALA_HOME:-}" ] && [ -d "${IMPALA_HOME}" ]; then
  _signals_root="$(cd "${IMPALA_HOME}/../.." && pwd)"
else
  # This file lives at components/impala/bin/ when installed
  _signals_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"
fi
export RANGER_HOME_OVERRIDE="${RANGER_HOME_OVERRIDE:-${_signals_root}/.devenv/ranger/admin}"
# Project Maven store for FE (never ~/.m2). devenv tasks and enterShell set the same.
export SIG_MAVEN_REPO="${SIG_MAVEN_REPO:-${_signals_root}/.devenv/m2}"
# Maven 3.9+ honors MAVEN_ARGS; ensure FE resolve/installs stay under .devenv/m2 even
# when buildall is invoked outside `devenv tasks run impala:build`.
case " ${MAVEN_ARGS:-} " in
  *" -Dmaven.repo.local="*) ;;
  *) export MAVEN_ARGS="${MAVEN_ARGS:-} -Dmaven.repo.local=${SIG_MAVEN_REPO}" ;;
esac

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
