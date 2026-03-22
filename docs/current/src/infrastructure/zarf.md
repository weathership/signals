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
- ML model artifacts served from local filesystem or S3 via VPC endpoint

## ML Model Artifacts

The sigint classification pipeline uses a sentence-transformer model (`all-MiniLM-L6-v2`, ~80MB) for embedding classification. In air-gap environments, this model must be pre-cached — the pipeline cannot download from HuggingFace at runtime.

### Model Cache Bootstrap

```bash
# Pre-download model to build/models/ (runs with HF_HUB_OFFLINE=0)
just cache-models
# or: devenv tasks run sigint:cache-models
```

This downloads the model once to `build/models/`. All subsequent pipeline runs use the local cache with zero external network calls.

### Runtime Isolation

The devenv shell configures air-gap isolation automatically:

| Variable | Value | Purpose |
|----------|-------|---------|
| `HF_HUB_OFFLINE` | `1` | Prevent HuggingFace Hub API calls |
| `SENTENCE_TRANSFORMERS_HOME` | `build/models` | Local model cache directory |

The HOCON config (`config/base.conf`) mirrors this with `embedding.cache_dir = "build/models"`, which flows through `PipelineConfig` → `EmbeddingClassifierConfig` → `SentenceTransformer(cache_folder=...)`.

### Packaging for Zarf

For fully disconnected deployments, the model cache can be included in Zarf packages:

1. **Container image bake-in**: Copy `build/models/` into the sigint container image at build time
2. **S3 staging**: Upload `build/models/` to S3, download via VPC endpoint during deployment
3. **Zarf data injection**: Add as a Zarf `files` component for direct filesystem staging

```yaml
# Example zarf.yaml component for model artifacts
components:
  - name: sigint-models
    required: true
    files:
      - source: build/models/
        target: /opt/sigint/models/
```

Set `SENTENCE_TRANSFORMERS_HOME=/opt/sigint/models/` and `HF_HUB_OFFLINE=1` in the container environment to complete the air-gap chain
