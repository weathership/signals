# Platform Metaflow config

| File | Role |
|------|------|
| `platform.json` | Client Metaflow profile (service + RustFS S3) |

Architecture: `docs/current/src/architecture/metaflow-platform.md`  
Deploy: `just metaflow-platform` → `scripts/metaflow_platform_bootstrap.sh`  
Manifests: `config/k8s/metaflow/`  
Submodule: `components/metaflow` (`weathership/oss-metaflow` **`rch/devenv`**)

## Lab endpoints

| Surface | URL |
|---------|-----|
| Metadata service (host) | `http://127.0.0.1:30180` NodePort · also `:8080` with hostNetwork |
| In-cluster service | `http://metaflow-service.metaflow.svc:8080` |
| Datastore | `s3://metaflow/metaflow` via RustFS `:9010` |

**Lab note:** devenv Postgres listens on `127.0.0.1` only, so the metadata
Deployment uses `hostNetwork: true` and `MF_METADATA_DB_HOST=127.0.0.1:5455`.
Production would use ClusterIP to a real PG Service (no hostNetwork).

## Client setup

```bash
mkdir -p ~/.metaflowconfig
cp config/metaflow/platform.json ~/.metaflowconfig/config.json
export METAFLOW_SERVICE_URL=http://127.0.0.1:30180
# Optional: point AWS SDK at RustFS for local runs
export AWS_ACCESS_KEY_ID=rustfsadmin
export AWS_SECRET_ACCESS_KEY=rustfsadmin
export AWS_ENDPOINT_URL_S3=http://127.0.0.1:9010
```
