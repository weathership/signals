#!/usr/bin/env bash
# Remove cybersec-dask app surface so signals-federation takes precedence.
# Does NOT remove zarf init/registry by default (use --full-zarf for that).
#
# NOTE: Sibling repos (e.g. zndx/aegir Tilt Metaflow) will recreate purged
# namespaces if their devenv/Tilt is still running. Stop those first:
#   (cd ~/local/src/zndx/aegir && devenv processes down)
# Longer-term: all K8s work on this node should go through federation + YK
# queues so scarce capacity is not contended by independent apply loops.
set -euo pipefail
KUBECONFIG="${KUBECONFIG:-$HOME/.kube/rke2.yaml}"
export KUBECONFIG
k() { kubectl --kubeconfig "$KUBECONFIG" "$@"; }

FULL_ZARF=0
[[ "${1:-}" == "--full-zarf" ]] && FULL_ZARF=1

NS_REMOVE=(
  dask dask-operator jupyterhub panel-viz
  aegir-metaflow
  # do not remove knative-serving / yunikorn / federation-* here —
  # those belong to signals-federation (use zarf package remove)
)
echo "Removing app namespaces (cybersec surface)..."
if pgrep -af '[t]ilt' >/dev/null 2>&1; then
  echo "WARNING: tilt process(es) still running — purged namespaces may be recreated." >&2
  echo "  Stop sibling devenvs (e.g. aegir: devenv processes down) then re-run." >&2
fi
for ns in "${NS_REMOVE[@]}"; do
  if k get ns "$ns" &>/dev/null; then
    echo "  delete ns/$ns"
    k delete ns "$ns" --wait=false || true
  fi
done

# default ns: remove known cybersec/metaflow deploys if present
for dep in metaflow-service metaflow-ui metaflow-ui-static argo-workflows-server argo-workflows-workflow-controller; do
  k -n default delete deploy "$dep" --ignore-not-found --wait=false 2>/dev/null || true
done
k -n default delete svc metaflow-service metaflow-ui metaflow-ui-static argo-workflows-server devenv-minio devenv-postgres --ignore-not-found 2>/dev/null || true

if [[ "$FULL_ZARF" -eq 1 ]]; then
  echo "FULL: zarf package remove (if available)..."
  zarf package remove cybersec-dask --confirm 2>/dev/null || true
  zarf package remove cybersec-k8s-dashboard --confirm 2>/dev/null || true
fi

echo "Done. Remaining:"
k get ns
k get pods -A --field-selector=status.phase!=Succeeded 2>/dev/null | head -40
