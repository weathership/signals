# gRPC Engine

The server-side agent engine processes user instructions from the WASM terminal and orchestrates analytical workloads across the visualization and data infrastructure layers.

## Responsibilities

- Accept gRPC connections from WASM terminal clients
- Parse and interpret user instructions
- Direct the HoloViews/Datashader/Dask pipeline to recompute views
- Manage the extension registry (algorithm loading, capability inventory)
- Execute self-improvement cycles with quantitative objectives
- Stream responses and updated visualizations back to clients

## Service Architecture

The engine runs as a Kubernetes Deployment (`signals-engine` namespace) with a ClusterIP Service exposing port 50051 for gRPC traffic.

```
signals-engine.signals-engine.svc.cluster.local:50051
```

In development, Tilt provides port-forwarding for local iteration:

```bash
KUBECONFIG=~/.kube/rke2.yaml tilt up
# gRPC accessible at localhost:50051
```

## Health Checks

The engine implements the gRPC health checking protocol:

- **Readiness probe** — gRPC health check on port 50051 (5s initial, 10s period)
- **Liveness probe** — gRPC health check on port 50051 (15s initial, 20s period)

## Deployment

| Mode | Engine Location |
|------|----------------|
| Laptop/Workstation | Local process or k3d pod |
| Hybrid | Local engine, remote Dask cluster |
| Full AWS | RKE2 pod via Ansible or Zarf |

See [Deployment Modes](./deployment.md) for details.
