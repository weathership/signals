#!/usr/bin/env bash
# Redeploy the Signals-owned Airflow DAG files without re-running the whole
# platform bootstrap: recreate the signals-airflow-dags ConfigMap from the
# repo and `helm upgrade` the release so new subPath mounts in
# values-signals.yaml land (a DAG file is only visible to the dag-processor
# once BOTH the ConfigMap key and the mount exist).
#
# Idempotent. Uses the SAME secrets file and helm arguments as
# airflow_platform_bootstrap.sh (the fernet/JWT/API keys are read, never
# regenerated). Airflow pods roll once; the CI DAGs and deferred coord_activity
# holds survive a restart (their state lives in the metadata DB).
#
# Usage: scripts/airflow_dags_deploy.sh [--no-helm]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_DIR="$ROOT/config/k8s/airflow"
EVENTING_DAGS="$ROOT/config/k8s/eventing/dags"
CHART_DIR="$ROOT/components/airflow/chart"
VALUES="$MANIFEST_DIR/values-signals.yaml"
SECRET_FILE="${AIRFLOW_SECRETS_FILE:-$ROOT/build/config/airflow-secrets.env}"
RELEASE="${AIRFLOW_HELM_RELEASE:-airflow}"
NAMESPACE="${AIRFLOW_NAMESPACE:-airflow}"
TIMEOUT="${AIRFLOW_BOOTSTRAP_TIMEOUT:-600}"
AF_DB_USER="${AIRFLOW_DB_USER:-airflow}"
AF_DB_PASS="${AIRFLOW_DB_PASSWORD:-airflow}"
AF_DB_NAME="${AIRFLOW_DB_NAME:-airflow}"
export KUBECONFIG="${KUBECONFIG:-$HOME/.config/kube/rke2.yaml}"

info() { echo "airflow-dags: $*"; }
die() { echo "ERROR: airflow-dags: $*" >&2; exit 1; }

command -v kubectl >/dev/null || die "kubectl not found"
[[ -f "$SECRET_FILE" ]] || die "secrets file missing: $SECRET_FILE (run scripts/airflow_platform_bootstrap.sh once)"

# ── ConfigMap: every DAG file the values file mounts ─────────────────
cm_args=(
  --from-file=signals_ci_dag.py="$MANIFEST_DIR/dags/signals_ci_dag.py"
  --from-file=signals_smoke_dag.py="$MANIFEST_DIR/dags/signals_smoke_dag.py"
  --from-file=coord_activity_dag.py="$MANIFEST_DIR/dags/coord_activity_dag.py"
  --from-file=coord_signals.py="$MANIFEST_DIR/plugins/coord_signals.py"
  --from-file=coord_lease.py="$MANIFEST_DIR/plugins/coord_lease.py"
  --from-file=gaius_article_curate_dag.py="$MANIFEST_DIR/dags/gaius_article_curate_dag.py"
)
for f in signals_eventing_ci_dag.py signals_eventing_smoke_dag.py; do
  [[ -f "$EVENTING_DAGS/$f" ]] && cm_args+=(--from-file="$f=$EVENTING_DAGS/$f")
done
info "applying ConfigMap signals-airflow-dags"
kubectl -n "$NAMESPACE" create configmap signals-airflow-dags "${cm_args[@]}" \
  --dry-run=client -o yaml | kubectl apply -f -

# Every mounted subPath must be a ConfigMap key, or the pods stick in ContainerCreating.
mounted="$(grep -oE 'subPath: [a-z_]+\.py' "$VALUES" | awk '{print $2}' | sort -u)"
keys="$(kubectl -n "$NAMESPACE" get configmap signals-airflow-dags -o jsonpath='{.data}' \
  | python3 -c 'import sys,json; print("\n".join(sorted(json.load(sys.stdin).keys())))')"
for m in $mounted; do
  grep -qx "$m" <<<"$keys" || die "values mounts $m but the ConfigMap has no such key"
done

if [[ "${1:-}" == "--no-helm" ]]; then
  info "ConfigMap applied; skipping helm upgrade (--no-helm)"
  exit 0
fi

command -v helm >/dev/null || die "helm not found"
# shellcheck source=/dev/null
. "$SECRET_FILE"
[[ -n "${AIRFLOW_FERNET_KEY:-}" && -n "${AIRFLOW_API_SECRET_KEY:-}" && -n "${AIRFLOW_JWT_SECRET:-}" ]] \
  || die "incomplete secrets in $SECRET_FILE"

info "helm upgrade $RELEASE (chart $CHART_DIR, values $VALUES)"
helm upgrade --install "$RELEASE" "$CHART_DIR" \
  --namespace "$NAMESPACE" \
  -f "$VALUES" \
  --set-string "data.metadataConnection.user=${AF_DB_USER}" \
  --set-string "data.metadataConnection.pass=${AF_DB_PASS}" \
  --set-string "data.metadataConnection.db=${AF_DB_NAME}" \
  --set-string "data.metadataConnection.host=signals-postgres" \
  --set-string "fernetKey=${AIRFLOW_FERNET_KEY}" \
  --set-string "apiSecretKey=${AIRFLOW_API_SECRET_KEY}" \
  --set-string "jwtSecret=${AIRFLOW_JWT_SECRET}" \
  --timeout "${TIMEOUT}s" \
  --wait=false

for d in airflow-api-server airflow-scheduler airflow-dag-processor airflow-triggerer; do
  info "rollout $d"
  kubectl -n "$NAMESPACE" rollout status "deploy/$d" --timeout="${TIMEOUT}s"
done
info "done — the dag-processor parses new files within its refresh interval"
