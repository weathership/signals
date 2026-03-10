# Ansible Roles

Configuration management for RKE2 clusters and application services lives in `infra/aws/ansible/`.

## Directory Structure

```
infra/aws/ansible/
├── group_vars/all.yml        # Shared variables
├── inventory/
│   └── hosts.example         # Template (tofu-generated in practice)
├── playbooks/
│   ├── site.yml              # Full stack deployment
│   ├── dask-only.yml         # Standalone Dask
│   ├── airgap-deploy.yml     # Zarf air-gap
│   ├── teardown.yml          # Clean workloads
│   └── validate.yml          # Health checks
└── roles/
    ├── common/               # Base node setup
    ├── rke2-server/          # Control plane
    ├── rke2-agent/           # Workers
    ├── dask/                 # Dask operator + cluster
    ├── jupyterhub/           # JupyterHub
    ├── signals-engine/       # gRPC engine
    ├── cloudflare-tunnel/    # Ingress
    └── zarf-deploy/          # Air-gap orchestrator
```

## Roles

### common

Prepares Ubuntu 24.04 nodes for RKE2:
- System packages (iptables, open-iscsi, nfs-common)
- Kernel modules (br_netfilter, overlay)
- Sysctl tuning for Dask workloads (vm.max_map_count, somaxconn)
- Swap disabled, data volume formatted and mounted (workers)

### rke2-server

Installs RKE2 control plane:
- Downloads and runs official RKE2 installer
- Configures Canal CNI, TLS SANs, disables default ingress
- First server: waits for node token, propagates to all cluster members
- Additional servers: joins existing cluster with token

### rke2-agent

Installs RKE2 worker nodes:
- Fetches node token from control plane automatically
- Configures node labels (`dask.org/node-type=worker`, `signals.io/role=compute`)
- Joins the cluster

### dask

Deploys Dask via Helm:
- Adds Dask Helm repository
- Installs dask-kubernetes-operator
- Deploys DaskCluster CRD with configurable worker replicas, memory limits, and spill-to-disk
- Waits for scheduler pod to be ready

### jupyterhub

Deploys JupyterHub via Helm:
- Dummy authenticator for development (password: `signals`)
- Singleuser image shared with Dask workers
- ClusterIP service (accessed via Cloudflare Tunnel)

### signals-engine

Deploys the gRPC engine:
- Namespace, Deployment, and Service
- gRPC health check probes (readiness + liveness)
- Configurable resource limits

### cloudflare-tunnel

Deploys cloudflared for Zero Trust ingress:
- Validates tunnel token and ID (from OpenTofu outputs)
- Creates credentials Secret and config ConfigMap
- Routes: Dask dashboard, JupyterHub, Signals Engine
- 2 replicas with health checks

### zarf-deploy

4-phase air-gap deployment orchestrator:
1. **Stage** — copy Zarf binary and packages to control plane
2. **Init** — create PVs, initialize Zarf registry
3. **Deploy** — deploy application package with variables
4. **Verify** — check all components running

## Usage

```bash
cd infra/aws/ansible

# Full stack deployment
ansible-playbook playbooks/site.yml

# Deploy only Dask
ansible-playbook playbooks/dask-only.yml

# Air-gap deployment
ansible-playbook playbooks/airgap-deploy.yml

# Teardown workloads (keep RKE2)
ansible-playbook playbooks/teardown.yml

# Post-deployment validation
ansible-playbook playbooks/validate.yml
```
