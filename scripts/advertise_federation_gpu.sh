#!/usr/bin/env bash
# Advertise federation.zndx.org/gpu on a node (host-held GPU claim token).
# Not a device plugin: does not bind CUDA into pods. Lab oneshot, not a CI gate.
set -euo pipefail

KEY="federation.zndx.org/gpu"
# JSON pointer: / → ~1
PTR="/status/capacity/federation.zndx.org~1gpu"
APTR="/status/allocatable/federation.zndx.org~1gpu"
COUNT="${SIGNALS_FEDERATION_GPU_COUNT:-6}"

if [[ -n "${SIGNALS_FEDERATION_GPU_NODE:-}" ]]; then
  NODE="$SIGNALS_FEDERATION_GPU_NODE"
else
  NODE="$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')"
fi

if [[ -z "$NODE" ]]; then
  echo "advertise_federation_gpu: no node" >&2
  exit 1
fi

echo "advertise_federation_gpu: node=$NODE $KEY=$COUNT"
kubectl patch node "$NODE" --subresource=status --type=json --patch "$(
  cat <<EOF
[
  {"op":"add","path":"$PTR","value":"$COUNT"},
  {"op":"add","path":"$APTR","value":"$COUNT"}
]
EOF
)"
kubectl get node "$NODE" -o jsonpath="{.status.allocatable['federation\.zndx\.org/gpu']}{'\n'}"
