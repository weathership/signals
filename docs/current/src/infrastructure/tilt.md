# Dev Iteration (Tilt)

Tilt enables rapid development iteration on Kubernetes by watching source files and live-syncing changes into running pods.

## Strategy

The Tiltfile uses a two-tier approach:

| Tier | Trigger | Action | Speed |
|------|---------|--------|-------|
| **Live update** | Source file changes (`.rs`, `.py`) | Sync into running pod | ~3-5s |
| **Full rebuild** | Dockerfile or dependency changes | Podman build + push | ~30-60s |

## Configuration

The `Tiltfile` at project root configures:

- **Image build**: Custom build using `tilt/build-and-push.sh` (Podman-based)
- **K8s overlay**: `tilt/engine-dev.yaml` overrides the production deployment with dev settings
- **Port forwards**: gRPC engine on `localhost:50051`

## Usage

```bash
# With RKE2
KUBECONFIG=~/.kube/rke2.yaml tilt up

# With k3d
KUBECONFIG=~/.kube/k3d.yaml tilt up
```

Tilt will:
1. Build the signals-engine image using Podman
2. Push to the local registry (127.0.0.1:31999)
3. Apply the dev overlay to the cluster
4. Watch for source changes and live-sync

## Dev Overlay

The `tilt/engine-dev.yaml` configures the engine for development:

- Single replica
- `RUST_LOG=debug` for verbose logging
- Relaxed resource limits (2Gi memory, 2 CPU)

## Files

| File | Purpose |
|------|---------|
| `Tiltfile` | Tilt configuration (image build, resources, port forwards) |
| `tilt/engine-dev.yaml` | Dev Kubernetes overlay for signals-engine |
| `tilt/build-and-push.sh` | Podman build and push script |
