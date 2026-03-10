# Air-Gap (Zarf)

Zarf enables deployment to disconnected (air-gap) environments by packaging container images, Helm charts, and manifests into a single archive that can be transferred to isolated networks.

## Package Definition

The Zarf package (`zarf/zarf.yaml`) defines the following components:

| Component | Required | Description |
|-----------|----------|-------------|
| `signals-images` | Yes | Core container images (Dask, operator, engine) |
| `dask-operator` | Yes | Dask Kubernetes Operator Helm chart |
| `dask-cluster` | Yes | DaskCluster CRD manifest |
| `signals-engine` | No (default: on) | gRPC engine deployment |
| `jupyterhub` | No (default: on) | JupyterHub Helm chart |
| `ingress` | No (default: on) | Ingress resources |

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DASK_WORKER_REPLICAS` | `4` | Worker count |
| `DASK_SPILL_DIR` | `/tmp/dask-spill` | Spill-to-disk path |
| `S3_ENDPOINT` | (empty) | S3-compatible endpoint |
| `S3_BUCKET` | `signals-360-data` | Data bucket name |
| `S3_REGION` | `us-east-1` | AWS region |

## Workflow

### Build the package

```bash
cd zarf

# Download Helm charts to charts/
helm pull dask/dask-kubernetes-operator --version 2024.1.0 -d charts/
helm pull jupyterhub/jupyterhub --version 4.0.0 -d charts/

# Create manifests
# ... (namespace.yaml, dask-cluster.yaml, engine.yaml, etc.)

# Build package
zarf package create --confirm
```

### Deploy to air-gap cluster

Using Ansible:

```bash
ansible-playbook playbooks/airgap-deploy.yml
```

Or manually:

```bash
# Stage on control plane
scp zarf signals-360-amd64.tar.zst user@cp:/opt/zarf/

# Initialize (creates internal registry)
zarf init --components=git-server --confirm

# Deploy
zarf package deploy signals-360-amd64.tar.zst \
  --set DASK_WORKER_REPLICAS=4 \
  --set S3_BUCKET=signals-360-data \
  --confirm
```

## Air-Gap Network Requirements

When `airgap_mode = true` in OpenTofu:

- NAT gateway is removed — no outbound internet from private subnet
- S3 access preserved via VPC gateway endpoint
- Container images served from Zarf's internal registry (port 31999)
- Git repos served from Zarf's internal Gitea instance
