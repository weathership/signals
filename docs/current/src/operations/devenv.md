# Development Environment

Signals 360 uses [devenv](https://devenv.sh/) (Nix-based) with direnv for automatic shell activation.

## Entering the Environment

```bash
devenv shell          # Manual entry
# or automatic via direnv when cd-ing into the repo
```

## Starting Services

```bash
devenv up             # Start PostgreSQL + Kerberos KDC
```

## Languages

| Language | Version | Purpose |
|----------|---------|---------|
| Rust | stable | Primary application language |
| Python | 3.12 | Tooling, Airflow; uv for package management |
| Java | 21 | ASF component builds (Maven enabled) |
| TypeScript/JS | latest | Frontend |

## Available Tasks

### Service Tasks

```bash
devenv tasks run signals:kdc-init    # Initialize KDC
devenv tasks run signals:kdc-reset   # Reset KDC database
```

### Documentation Tasks

```bash
devenv tasks run docs:build          # Build mdbook documentation
devenv tasks run docs:serve          # Serve docs with live reload
```

### Local Cluster Tasks (k8s:*)

```bash
devenv tasks run k8s:provision       # Create k3d cluster
devenv tasks run k8s:status          # Check cluster connectivity
devenv tasks run k8s:deploy-dask     # Deploy Dask operator + cluster
devenv tasks run k8s:deploy-jupyter  # Deploy JupyterHub
devenv tasks run k8s:forward         # Port-forward services
devenv tasks run k8s:destroy         # Delete k3d cluster
```

### AWS Cloud Tasks (aws:*)

```bash
devenv tasks run aws:provision       # OpenTofu apply (VPC, EC2, S3)
devenv tasks run aws:inventory       # Generate Ansible inventory
devenv tasks run aws:deploy          # Full stack: RKE2 + Dask + services
devenv tasks run aws:verify          # Post-deployment health checks
devenv tasks run aws:ssh             # SSH to bastion host
devenv tasks run aws:destroy         # Destroy infrastructure (preserves S3)
devenv tasks run aws:teardown        # Full teardown including S3
```

## Included Tooling

The devenv environment includes tools for all deployment modes:

| Category | Tools |
|----------|-------|
| **Core** | git, gh, jq |
| **Security** | krb5, cyrus_sasl, openssl |
| **ASF Build** | cmake, ninja, gcc, protobuf, flatbuffers |
| **Kubernetes** | kubectl, helm, tilt, k9s, k3d |
| **Cloud** | awscli2, opentofu, ansible |
| **Air-Gap** | zarf, conftest, podman |
| **Ingress** | cloudflared |
| **WASM** | wasmtime, wasm-pack, wasm-bindgen-cli, binaryen |
| **Data** | grpcurl, dbmate |
| **Docs** | mdbook, mdbook-d2, d2, graphviz |

## BDD Testing

```bash
uv run behave                        # Run all BDD scenarios
uv run behave --dry-run              # Parse features without executing
uv run behave features/platform/     # Run platform scenarios only
```

See [Test Infrastructure](../scenarios/testing.md) for the tier system.
