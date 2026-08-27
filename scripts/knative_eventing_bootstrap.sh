#!/usr/bin/env bash
# M3: Knative Eventing (v1.23 aligned with Serving) + platform Broker + Airflow sink.
# No Argo. Metaflow/Gaius/etc. publish CloudEvents → Broker → airflow-dag-trigger.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MANIFEST_DIR="$ROOT/zarf/federation/manifests/knative"
PLATFORM_DIR="$ROOT/config/k8s/eventing"
AIRFLOW_DAGS_CM_NS="${AIRFLOW_NAMESPACE:-airflow}"

pick_kubeconfig() {
  local c
  for c in \
    "${KUBECONFIG:-}" \
    "${HOME}/.kube/rke2.yaml" \
    "${HOME}/.kube/config"; do
    [[ -n "$c" && -r "$c" ]] || continue
    export KUBECONFIG="$c"
    return 0
  done
  export KUBECONFIG="${HOME}/.kube/rke2.yaml"
  return 1
}

info() { echo "eventing-bootstrap: $*"; }
die() { echo "ERROR: eventing-bootstrap: $*" >&2; exit 1; }
k() { kubectl --kubeconfig "$KUBECONFIG" "$@"; }

pick_kubeconfig || true
info "KUBECONFIG=$KUBECONFIG"
command -v kubectl >/dev/null || die "kubectl not found"
k get ns >/dev/null 2>&1 || die "cannot reach cluster"

# Serving must exist (signals-federation)
k get ns knative-serving >/dev/null 2>&1 || die "knative-serving missing — run federation preflight first"

for f in eventing-crds.yaml eventing-core.yaml in-memory-channel.yaml mt-channel-broker.yaml; do
  [[ -f "$MANIFEST_DIR/$f" ]] || die "missing $MANIFEST_DIR/$f — re-run fetch or git pull"
done

# Annotate eventing ns to skip Zarf rewrite when created by manifests
info "applying Eventing CRDs"
k apply -f "$MANIFEST_DIR/eventing-crds.yaml"
info "applying Eventing core"
k apply -f "$MANIFEST_DIR/eventing-core.yaml"
# Ignore Zarf on knative-eventing (ns + pod templates — agent rewrites gcr.io otherwise)
k annotate ns knative-eventing zarf.dev/agent=ignore --overwrite 2>/dev/null || true
k label ns knative-eventing zarf.dev/agent=ignore --overwrite 2>/dev/null || true

# Patch all Eventing workloads so Zarf admission does not rewrite images to :31999
zarf_ignore_ns() {
  local ns="$1"
  local r
  for r in $(k -n "$ns" get deploy,sts -o name 2>/dev/null); do
    k -n "$ns" patch "$r" --type strategic -p \
      '{"spec":{"template":{"metadata":{"annotations":{"zarf.dev/agent":"ignore"},"labels":{"zarf.dev/agent":"ignore"}}}}}' \
      >/dev/null 2>&1 || true
  done
}
# Idempotent: only pods the Zarf agent already rewrote (127.0.0.1:31999/…) need replacing.
# A blanket `delete pods --all --force` on every run rolled the whole eventing control
# plane, un-readied the Broker, and (via stack-preflight → signals-ui restart) looped.
zarf_rewritten_pods() {
  local ns="$1"
  k -n "$ns" get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}' 2>/dev/null \
    | awk '/:31999\//{print $1}'
}
delete_zarf_rewritten_pods() {
  local ns="$1" pods
  pods="$(zarf_rewritten_pods "$ns" | tr '\n' ' ')"
  if [[ -n "${pods// /}" ]]; then
    info "replacing Zarf-rewritten pods in ns/$ns: $pods"
    # shellcheck disable=SC2086
    k -n "$ns" delete pods $pods --force --grace-period=0 2>/dev/null || true
  fi
}
zarf_ignore_ns knative-eventing
delete_zarf_rewritten_pods knative-eventing

info "waiting for eventing controller/webhook..."
k -n knative-eventing rollout status deploy/eventing-controller --timeout=300s
k -n knative-eventing rollout status deploy/eventing-webhook --timeout=300s

info "applying in-memory channel + MT channel broker"
k apply -f "$MANIFEST_DIR/in-memory-channel.yaml"
k apply -f "$MANIFEST_DIR/mt-channel-broker.yaml"
zarf_ignore_ns knative-eventing
delete_zarf_rewritten_pods knative-eventing
k -n knative-eventing rollout status deploy/imc-controller --timeout=300s 2>/dev/null \
  || k -n knative-eventing wait --for=condition=Available deploy -l messaging.knative.dev/channel=InMemoryChannel --timeout=300s 2>/dev/null \
  || info "WARN: imc-controller wait skipped"
k -n knative-eventing rollout status deploy/mt-broker-controller --timeout=300s 2>/dev/null || true
k -n knative-eventing rollout status deploy/mt-broker-filter --timeout=300s 2>/dev/null || true
k -n knative-eventing rollout status deploy/mt-broker-ingress --timeout=300s 2>/dev/null || true

# Platform sink + broker
info "applying platform signals-events resources"
k apply -f "$PLATFORM_DIR/namespace.yaml"
k annotate ns signals-events zarf.dev/agent=ignore --overwrite 2>/dev/null || true
k apply -f "$PLATFORM_DIR/sink-configmap.yaml"
k apply -f "$PLATFORM_DIR/sink-deployment.yaml"
k apply -f "$PLATFORM_DIR/broker-trigger.yaml"

info "waiting for airflow-dag-trigger..."
k -n signals-events rollout status deploy/airflow-dag-trigger --timeout=180s

# Ensure eventing CI DAGs are in Airflow ConfigMap (ci primary + legacy smoke dual-map)
if k get ns "$AIRFLOW_DAGS_CM_NS" >/dev/null 2>&1; then
  info "updating Airflow DAG ConfigMap (signals_ci + signals_eventing_ci + legacy)"
  cm_result="$(k -n "$AIRFLOW_DAGS_CM_NS" create configmap signals-airflow-dags \
    --from-file=signals_ci_dag.py="$ROOT/config/k8s/airflow/dags/signals_ci_dag.py" \
    --from-file=signals_eventing_ci_dag.py="$PLATFORM_DIR/dags/signals_eventing_ci_dag.py" \
    --from-file=signals_smoke_dag.py="$ROOT/config/k8s/airflow/dags/signals_smoke_dag.py" \
    --from-file=signals_eventing_smoke_dag.py="$PLATFORM_DIR/dags/signals_eventing_smoke_dag.py" \
    --dry-run=client -o yaml | k apply -f -)"
  echo "$cm_result"
  # subPath mounts do not refresh in place: restart dag-processor only when the CM changed.
  if [[ "$cm_result" != *unchanged* ]]; then
    info "DAG ConfigMap changed — restarting dag-processor"
    k -n "$AIRFLOW_DAGS_CM_NS" rollout restart deploy -l component=dag-processor 2>/dev/null \
      || k -n "$AIRFLOW_DAGS_CM_NS" delete pod -l component=dag-processor --force --grace-period=0 2>/dev/null \
      || true
  fi
else
  info "WARN: ns/$AIRFLOW_DAGS_CM_NS missing — skip DAG ConfigMap (run just airflow-platform first)"
fi

# Broker ready
info "waiting for Broker default Ready..."
for i in $(seq 1 60); do
  ready=$(k -n signals-events get broker default -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)
  if [[ "$ready" == "True" ]]; then
    break
  fi
  sleep 3
  if [[ "$i" -eq 60 ]]; then
    k -n signals-events get broker,trigger,pods -o wide || true
    die "Broker default not Ready"
  fi
done

ingress=$(k -n signals-events get broker default -o jsonpath='{.status.address.url}' 2>/dev/null || true)
info "OK — Knative Eventing platform ready"
info "  Broker: signals-events/default"
info "  Ingress: ${ingress:-<pending>}"
info "  Sink:    signals-events/airflow-dag-trigger"
info "  CI gate: just airflow-eventing-ci"
info "  Publish: scripts/signals_events_publish.sh dev.signals.eventing.ci"
exit 0
