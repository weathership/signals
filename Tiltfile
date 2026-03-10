# -*- mode: python -*-
# Tiltfile for iterating on Signals Engine + HoloViews/Datashader on RKE2/k3d
#
# Two-tier strategy:
#   Tier 1 (live_update): Edit .py/.rs files → ~3-5s sync into running pod
#   Tier 2 (full rebuild): Edit Dockerfile/requirements → podman build + push
#
# Usage:
#   KUBECONFIG=~/.kube/rke2.yaml tilt up       # RKE2
#   KUBECONFIG=~/.kube/k3d.yaml tilt up         # k3d

# --- Config ---
REGISTRY = '127.0.0.1:31999'
ENGINE_IMAGE = REGISTRY + '/signals-engine'

# Use existing cluster (RKE2 or k3d)
allow_k8s_contexts(k8s_context())

# --- Image build ---
custom_build(
    ENGINE_IMAGE,
    'tilt/build-and-push.sh $EXPECTED_REF',
    deps=[
        'Cargo.toml',
        'Cargo.lock',
        'src/',
    ],
    skips_local_docker=True,
    live_update=[
        fall_back_on([
            'Cargo.toml',
            'Cargo.lock',
        ]),
        sync('src/', '/app/src/'),
    ],
)

# --- K8s resources (overlay on deployed resources) ---
k8s_yaml('tilt/engine-dev.yaml')

# signals-engine: gRPC server
k8s_resource(
    'signals-engine',
    port_forwards=[
        port_forward(50051, 50051, host='0.0.0.0', name='grpc'),
    ],
    labels=['signals'],
)
