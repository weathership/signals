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
# Ensure MiniLM via HF_HOME / SENTENCE_TRANSFORMERS_HOME (RAID preferred)
just cache-models
# or: devenv tasks run sigint:cache-models
```

Lab hosts pin caches on RAID (`HF_HOME`, `HF_HUB_CACHE`, `SENTENCE_TRANSFORMERS_HOME`).
`just cache-models` **skips download** when MiniLM is already there and does not copy into
`build/models/` (root disk is tight). Tree-local `build/models` is only a last-resort
fallback when no shared cache is configured.

### Runtime Isolation

The devenv shell configures air-gap isolation automatically:

| Variable | Value | Purpose |
|----------|-------|---------|
| `HF_HUB_OFFLINE` | `1` | Prevent HuggingFace Hub API calls |
| `HF_HOME` | e.g. `/raid/cache/huggingface` | Primary HF cache root |
| `HF_HUB_CACHE` | e.g. `/raid/cache/rch/huggingface` | Hub package cache (may differ from `$HF_HOME/hub`) |
| `SENTENCE_TRANSFORMERS_HOME` | e.g. `/raid/cache/sentence-transformers` | ST model blobs |
| `SIGINT_EMBEDDING_CACHE_DIR` | defaults to `$SENTENCE_TRANSFORMERS_HOME` | HOCON `embedding.cache_dir` → `SentenceTransformer(cache_folder=...)` |

HOCON resolves `embedding.cache_dir` as: default → `${?SENTENCE_TRANSFORMERS_HOME}` → `${?SIGINT_EMBEDDING_CACHE_DIR}` (last set wins).

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
