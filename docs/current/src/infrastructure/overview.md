# Infrastructure Overview

The infrastructure stack is layered: OpenTofu provisions cloud resources, Ansible configures them, Zarf packages for air-gap, Tilt enables dev iteration, and OPA policies provide guardrails.

## Layers

| Layer | Tool | Directory | Purpose |
|-------|------|-----------|---------|
| **Provisioning** | OpenTofu | `infra/aws/tofu/` | AWS VPC, EC2, S3, Cloudflare Tunnel |
| **Configuration** | Ansible | `infra/aws/ansible/` | RKE2 install, Dask, services, ingress |
| **Packaging** | Zarf | `zarf/` | Air-gap Kubernetes deployment |
| **Dev Iteration** | Tilt | `tilt/`, `Tiltfile` | Live-reload development on RKE2/k3d |
| **Policy** | OPA/Conftest | `policy/` | IaC and K8s guardrails |

## Deployment Flow

```
OpenTofu apply
    │
    ▼
Generate Ansible inventory from Tofu state
    │
    ▼
Ansible site.yml
    ├── common (node prep)
    ├── rke2-server (control plane)
    ├── rke2-agent (workers)
    ├── dask (operator + cluster)
    ├── signals-engine (gRPC)
    ├── jupyterhub (notebooks)
    └── cloudflare-tunnel (ingress)
    │
    ▼
Validate deployment
```

For air-gap environments, the Ansible flow uses the `zarf-deploy` role instead of individual service roles.

## Ansible Roles

| Role | Purpose |
|------|---------|
| `common` | Base node setup: packages, kernel modules, sysctl, data volumes |
| `rke2-server` | Control plane installation with token propagation |
| `rke2-agent` | Worker installation with automatic token fetch |
| `dask` | Helm-based Dask operator + DaskCluster CRD |
| `jupyterhub` | Helm-based JupyterHub with Dask integration |
| `signals-engine` | gRPC engine deployment + service |
| `cloudflare-tunnel` | cloudflared with config-driven ingress routing |
| `zarf-deploy` | 4-phase air-gap orchestrator (stage/init/deploy/verify) |

## Playbooks

| Playbook | Description |
|----------|-------------|
| `site.yml` | Full stack: RKE2 + Dask + Engine + JupyterHub + Ingress |
| `dask-only.yml` | Standalone Dask operator deploy |
| `airgap-deploy.yml` | Air-gap deployment via Zarf |
| `teardown.yml` | Remove workloads, preserve RKE2 cluster |
| `validate.yml` | Post-deployment health checks |

## Task Reference

### Local Cluster (k8s:*)

| Task | Description |
|------|-------------|
| `k8s:provision` | Create k3d cluster |
| `k8s:status` | Check cluster connectivity |
| `k8s:deploy-dask` | Deploy Dask operator + cluster |
| `k8s:deploy-jupyter` | Deploy JupyterHub |
| `k8s:forward` | Port-forward services |
| `k8s:destroy` | Delete k3d cluster |

### AWS Cloud (aws:*)

| Task | Description |
|------|-------------|
| `aws:provision` | OpenTofu apply (VPC, EC2, S3) |
| `aws:inventory` | Generate Ansible inventory from Tofu state |
| `aws:deploy` | Full stack: RKE2 + Dask + services |
| `aws:verify` | Post-deployment health checks |
| `aws:ssh` | SSH to bastion host |
| `aws:destroy` | Destroy infrastructure (preserves S3) |
| `aws:teardown` | Full teardown including S3 |
