#!/usr/bin/env bash
# One kinit of /tmp/krb5cc_impala. Airflow schedules the repeat
# (gaius_impala_krb_renew). This script must not loop.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$ROOT/.devenv/profile/bin:${PATH:-}"
# shellcheck source=scripts/signals_kerberos.sh
. "$ROOT/scripts/signals_kerberos.sh"
signals_impala_kinit "$ROOT"
