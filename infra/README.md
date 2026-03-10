# Infrastructure

Signals 360 supports four deployment modes, from local development to full cloud production.

## Deployment Modes

| Mode | Compute | K8s | Services | Setup Time |
|------|---------|-----|----------|------------|
| **Laptop** | Local | k3d (optional) | devenv | ~5 min |
| **Workstation** | Local | RKE2 (optional) | devenv + GPU | ~15 min |
| **Hybrid** | Local + AWS | RKE2 (local) + RKE2 (AWS) | Split | ~30 min |
| **Full AWS** | AWS EC2 | RKE2 | All remote | ~30 min |

### Laptop Development

Local-only with devenv services (PostgreSQL, KDC). Optional k3d cluster for Kubernetes workloads.

```bash
devenv up                              # Start PostgreSQL + KDC
devenv tasks run k8s:provision         # Optional: create k3d cluster
devenv tasks run k8s:deploy-dask       # Optional: deploy Dask on k3d
```

### Workstation

Local devenv with optional RKE2 for production-grade Kubernetes. Suitable for GPU-accelerated workloads.

```bash
devenv up                              # Start core services
# RKE2 managed externally or via system service
devenv tasks run k8s:deploy-dask       # Deploy Dask on RKE2
```

### Hybrid (Workstation + AWS)

Local development environment with AWS RKE2 cluster for distributed compute. Visualization and terminal run locally; heavy computation offloaded to AWS.

```bash
devenv up                              # Local services
devenv tasks run aws:provision         # Provision AWS infrastructure
devenv tasks run aws:deploy            # Deploy RKE2 + Dask on AWS
```

### Full AWS

Everything runs on AWS EC2 with RKE2. Access via Cloudflare Zero Trust.

```bash
devenv tasks run aws:provision         # VPC, EC2, IAM, S3
devenv tasks run aws:inventory         # Generate Ansible inventory
devenv tasks run aws:deploy            # Full stack deployment
devenv tasks run aws:verify            # Post-deployment checks
```

## Directory Structure

```
infra/
├── README.md                      # This file
├── aws/
│   ├── tofu/                      # OpenTofu IaC (VPC, EC2, S3, Cloudflare)
│   │   ├── versions.tf            # Provider version constraints
│   │   ├── provider.tf            # AWS + Cloudflare providers
│   │   ├── variables.tf           # Variable definitions
│   │   ├── terraform.tfvars       # Shared defaults
│   │   ├── vpc.tf                 # VPC, subnets, NAT, S3 endpoint
│   │   ├── security.tf            # Security groups (bastion, RKE2)
│   │   ├── ec2.tf                 # Bastion, control plane, workers
│   │   ├── s3.tf                  # Encrypted S3 data bucket
│   │   └── outputs.tf             # Bastion IP, node IPs, SSH key
│   └── ansible/                   # Configuration management
│       ├── group_vars/all.yml     # Shared variables
│       ├── inventory/             # Dynamic inventory (tofu-generated)
│       ├── playbooks/             # Deployment playbooks
│       │   ├── site.yml           # Full stack deployment
│       │   ├── dask-only.yml      # Standalone Dask deploy
│       │   ├── airgap-deploy.yml  # Air-gap via Zarf
│       │   ├── teardown.yml       # Clean workloads
│       │   └── validate.yml       # Post-deploy checks
│       └── roles/                 # Ansible roles
│           ├── common/            # Base node setup
│           ├── rke2-server/       # Control plane install
│           ├── rke2-agent/        # Worker install
│           ├── dask/              # Dask operator + cluster
│           ├── jupyterhub/        # JupyterHub
│           ├── signals-engine/    # gRPC engine
│           ├── cloudflare-tunnel/ # Cloudflare ingress
│           └── zarf-deploy/       # Air-gap orchestrator
└── benchmarks/                    # Performance benchmarking configs

zarf/                              # Air-gap Kubernetes packaging
├── zarf.yaml                      # Package definition
├── charts/                        # Vendored Helm charts
├── manifests/                     # K8s manifests
└── images/                        # Container image configs

tilt/                              # Tilt dev overlays for live-reload
├── engine-dev.yaml                # Dev overlay for signals-engine
└── build-and-push.sh              # Podman build script

policy/                            # OPA policy validation
├── tofu/                          # OpenTofu plan policies
│   ├── base.rego                  # Common helpers
│   ├── provision.rego             # Create guardrails
│   └── destroy.rego               # Delete guardrails
└── k8s/                           # Kubernetes policies
    └── base.rego                  # Tool + cluster validation
```

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
| `aws:provision` | OpenTofu apply (VPC, EC2, IAM, S3) |
| `aws:inventory` | Generate Ansible inventory from Tofu state |
| `aws:deploy` | Full stack: RKE2 + Dask + services |
| `aws:verify` | Post-deployment health checks |
| `aws:ssh` | SSH to bastion host |
| `aws:destroy` | Destroy infrastructure (preserves S3) |
| `aws:teardown` | Full teardown including S3 |
