#!/usr/bin/env bash
# Confirm local RKE2 has signals-federation control plane: YuniKorn + Knative.
# Used by devenv (`signals:federation-ready` before signals-ui) and just recipes.
#
# Exit 0 only when YK REST answers and Knative Serving controllers are Available.
# Optionally deploys the air-gap package if missing and the tarball is present.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Prefer a *readable* kubeconfig. System rke2.yaml is often root-only;
# lab copy lives at ~/.kube/rke2.yaml (or KUBECONFIG when readable).
pick_kubeconfig() {
  local c
  for c in \
    "${KUBECONFIG:-}" \
    "${HOME}/.kube/rke2.yaml" \
    "${HOME}/.kube/config" \
    /etc/rancher/rke2/rke2.yaml; do
    [[ -n "$c" && -r "$c" ]] || continue
    export KUBECONFIG="$c"
    return 0
  done
  export KUBECONFIG="${HOME}/.kube/rke2.yaml"
  return 1
}
pick_kubeconfig || true

YK_URL="${SIGNALS_YK_API_URL:-http://127.0.0.1:30080}"
# Strip trailing slash
YK_URL="${YK_URL%/}"
PKG="${SIGNALS_FEDERATION_PACKAGE:-/raid/signals/zarf-build/zarf-package-signals-federation-amd64-0.1.0.tar.zst}"
AUTO_DEPLOY="${SIGNALS_FEDERATION_AUTO_DEPLOY:-1}"
SKIP_CONVERGE="${SIGNALS_FEDERATION_SKIP_CONVERGE:-0}"

k() {
  kubectl --kubeconfig "$KUBECONFIG" "$@"
}

die() {
  echo "ERROR: federation preflight: $*" >&2
  exit 1
}

info() {
  echo "federation-preflight: $*"
}

yk_rest_ok() {
  curl -sf -m 5 "${YK_URL}/ws/v1/clusters" >/dev/null 2>&1
}

deploy_available() {
  local ns="$1" name="$2"
  local n
  n="$(k get deploy -n "$ns" "$name" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo 0)"
  [[ -n "$n" && "$n" != "0" ]]
}

ensure_yunikorn_nodeport() {
  # Lab: durable host reach for signals-ui (REST 30080, web 30889).
  k get svc yunikorn-service -n yunikorn &>/dev/null || return 0
  local typ
  typ="$(k get svc yunikorn-service -n yunikorn -o jsonpath='{.spec.type}' 2>/dev/null || true)"
  if [[ "$typ" != "NodePort" ]]; then
    info "patching yunikorn-service → NodePort 30080/30889"
    k patch svc yunikorn-service -n yunikorn --type=merge -p '{
      "spec": {
        "type": "NodePort",
        "ports": [
          {"name": "yunikorn-service", "port": 9080, "targetPort": 9080, "nodePort": 30080, "protocol": "TCP"},
          {"name": "yunikorn-service-web", "port": 9889, "targetPort": 9889, "nodePort": 30889, "protocol": "TCP"}
        ]
      }
    }' >/dev/null
  fi
}

cluster_surface_ok() {
  k get nodes --no-headers 2>/dev/null | grep -q Ready || return 1
  deploy_available yunikorn yunikorn-scheduler || return 1
  deploy_available knative-serving controller || return 1
  deploy_available knative-serving activator || return 1
  local stz
  stz="$(k get cm config-autoscaler -n knative-serving -o jsonpath='{.data.enable-scale-to-zero}' 2>/dev/null || true)"
  [[ "${stz,,}" == "true" ]] || return 1
  return 0
}

maybe_deploy_package() {
  [[ "$AUTO_DEPLOY" == "1" || "$AUTO_DEPLOY" == "true" ]] || return 1
  command -v zarf >/dev/null 2>&1 || {
    info "zarf not on PATH — cannot auto-deploy"
    return 1
  }
  [[ -f "$PKG" ]] || {
    info "package missing: $PKG"
    return 1
  }
  info "deploying signals-federation from $PKG"
  zarf package deploy "$PKG" --confirm
  ensure_yunikorn_nodeport
}

wait_yk_rest() {
  local i
  for i in $(seq 1 60); do
    if yk_rest_ok; then
      info "YK REST OK at ${YK_URL}/ws/v1/clusters"
      return 0
    fi
    sleep 2
  done
  return 1
}

# ── main ──────────────────────────────────────────────────────────
info "KUBECONFIG=$KUBECONFIG"
info "SIGNALS_YK_API_URL=$YK_URL"

if ! command -v kubectl >/dev/null 2>&1; then
  die "kubectl not found"
fi

if ! k get ns >/dev/null 2>&1; then
  die "cannot talk to cluster (KUBECONFIG=$KUBECONFIG). Is RKE2 up?"
fi

if ! cluster_surface_ok; then
  info "YK/Knative surface incomplete — attempting ensure"
  maybe_deploy_package || true
  # Short wait after deploy / for in-flight rollouts
  for i in $(seq 1 30); do
    cluster_surface_ok && break
    sleep 2
  done
fi

if ! cluster_surface_ok; then
  die "YuniKorn + Knative not Available on RKE2.
  Fix:
    1) export KUBECONFIG=~/.kube/rke2.yaml
    2) zarf package deploy $PKG --confirm
    3) cd zarf/federation && python3 -m converge verify
  Or re-run: just federation-ready"
fi

ensure_yunikorn_nodeport

if ! wait_yk_rest; then
  die "YK REST not reachable at $YK_URL (NodePort 30080 expected after federation deploy).
  Check: kubectl get svc -n yunikorn yunikorn-service
  curl -sS ${YK_URL}/ws/v1/clusters"
fi

if [[ "$SKIP_CONVERGE" != "1" ]] && [[ -d zarf/federation/converge ]]; then
  info "converge verify"
  (cd zarf/federation && python3 -m converge verify) || die "converge verify failed"
fi

info "OK — YuniKorn + Knative ready (YK REST $YK_URL)"
export SIGNALS_YK_API_URL="$YK_URL"
