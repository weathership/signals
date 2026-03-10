# Deployment Modes

Signals 360 supports four deployment modes, from local development to full cloud production.

| Mode | Compute | K8s | Services |
|------|---------|-----|----------|
| **Laptop** | Local | k3d (optional) | devenv |
| **Workstation** | Local | RKE2 (optional) | devenv + GPU |
| **Hybrid** | Local + AWS | RKE2 (local) + RKE2 (AWS) | Split |
| **Full AWS** | AWS EC2 | RKE2 | All remote |

## Laptop Development

Local-only with devenv services (PostgreSQL, KDC). Optional k3d cluster for Kubernetes workloads.

```bash
devenv up                              # Start PostgreSQL + KDC
devenv tasks run k8s:provision         # Optional: create k3d cluster
devenv tasks run k8s:deploy-dask       # Optional: deploy Dask on k3d
```

Best for: iterating on engine code, feature development, BDD scenarios at Tier 0-1.

## Workstation

Local devenv with optional RKE2 for production-grade Kubernetes. Suitable for GPU-accelerated workloads.

```bash
devenv up                              # Start core services
devenv tasks run k8s:deploy-dask       # Deploy Dask on RKE2
```

Best for: integration testing, GPU workloads, running Tier 2 scenarios.

## Hybrid (Workstation + AWS)

Local development environment with AWS RKE2 cluster for distributed compute. The engine and visualization run locally; heavy computation is offloaded to AWS.

```bash
devenv up                              # Local services
devenv tasks run aws:provision         # Provision AWS infrastructure
devenv tasks run aws:deploy            # Deploy RKE2 + Dask on AWS
```

Best for: distributed workloads that exceed local capacity, Tier 3 scenarios.

## Full AWS

Everything runs on AWS EC2 with RKE2. Access via Cloudflare Zero Trust (WARP device posture).

```bash
devenv tasks run aws:provision         # VPC, EC2, S3
devenv tasks run aws:inventory         # Generate Ansible inventory
devenv tasks run aws:deploy            # Full stack deployment
devenv tasks run aws:verify            # Post-deployment checks
```

Best for: production deployments, air-gap environments, Tier 3 full-stack validation.

## Air-Gap Variant

Any mode with Kubernetes can use Zarf for disconnected deployment. The air-gap variant removes the NAT gateway (`airgap_mode = true` in OpenTofu), relying on VPC endpoints for S3 access and the Zarf internal registry for container images.

```bash
devenv tasks run aws:provision         # With airgap_mode = true
ansible-playbook playbooks/airgap-deploy.yml
```

See [Air-Gap (Zarf)](../infrastructure/zarf.md) for details.

## Infrastructure Layers

Each deployment mode uses a subset of the infrastructure stack:

| Layer | Tool | Purpose |
|-------|------|---------|
| Provisioning | OpenTofu | AWS VPC, EC2, S3, Cloudflare |
| Configuration | Ansible | RKE2, Dask, services, tunnels |
| Packaging | Zarf | Air-gap K8s deployment |
| Dev Iteration | Tilt | Live-reload on RKE2/k3d |
| Policy | OPA/Conftest | Guardrails for IaC and K8s |

See the [Infrastructure](../infrastructure/overview.md) section for detailed documentation of each layer.
