# Infrastructure Scaffold Completion

Completed the full infrastructure directory scaffolding based on cybersec project patterns, adapted for Signals 360's four deployment modes.

## Files Created (57 total)

### OpenTofu (9 files) — previously created
- VPC with public/private subnets, conditional NAT (air-gap aware), S3 VPC endpoint
- Bastion (t3.small), control plane (m6i.xlarge), workers (r6i.xlarge) with data volumes
- Encrypted S3 data bucket with public access blocked
- Security groups: bastion (SSH from WARP CGNAT) + RKE2 cluster (intra-cluster + bastion access)

### Ansible (35 files)
- **group_vars/all.yml** — project config, RKE2 version, Dask worker settings
- **inventory/hosts.example** — template with bastion jump host ProxyCommand
- **5 playbooks**: site.yml (full stack), dask-only.yml, airgap-deploy.yml, teardown.yml, validate.yml
- **8 roles** with defaults, tasks, and templates:
  - `common` — Ubuntu node prep (packages, sysctl, kernel modules, data volumes)
  - `rke2-server` — control plane install with token propagation
  - `rke2-agent` — worker install with auto token fetch
  - `dask` — Helm operator + DaskCluster CRD with spill-to-disk
  - `jupyterhub` — Helm chart with Dask integration
  - `signals-engine` — gRPC engine deployment + service
  - `cloudflare-tunnel` — cloudflared with config-driven ingress routing
  - `zarf-deploy` — 4-phase air-gap orchestrator (stage/init/deploy/verify)

### Zarf (1 + 3 .gitkeep)
- **zarf.yaml** — air-gap package: dask-operator, dask-cluster, signals-engine, jupyterhub, ingress

### Tilt (3 files)
- **Tiltfile** — two-tier live_update for RKE2/k3d dev iteration
- **engine-dev.yaml** — dev overlay for signals-engine
- **build-and-push.sh** — podman build script

### OPA Policies (4 files)
- **tofu/base.rego** — common helpers (resource filtering, developer isolation, Owner tags)
- **tofu/provision.rego** — create guardrails (Owner tags, developer prefix, advisory warnings)
- **tofu/destroy.rego** — delete guardrails (ownership validation)
- **k8s/base.rego** — tool + cluster validation

### .gitignore Updates
Added: OpenTofu state/lock, Ansible cache/retry/inventory, Zarf artifacts, Rust target, k3d state

## Key Design Decisions
- Ubuntu 24.04 (Noble) instead of cybersec's RHEL (apt vs dnf in common role)
- Signals-engine role added (gRPC server — not present in cybersec)
- Simplified ingress: Cloudflare Tunnel only (no deprecated ngrok path)
- Zarf package includes signals-engine component alongside Dask + JupyterHub
