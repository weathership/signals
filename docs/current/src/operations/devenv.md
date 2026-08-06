# Development Environment

Signals 360 uses [devenv](https://devenv.sh/) (Nix-based) with direnv for automatic shell activation.

## Entering the Environment

```bash
devenv shell          # Manual entry
# or automatic via direnv when cd-ing into the repo
```

**Secrets:** SecretSpec is enabled in `devenv.yaml` (dotenv provider). Declarations
live in `secretspec.toml` — see [Secrets](./secrets.md). Non-secret Kerberos
identity (`KRB5_REALM=DEV.VISTA.ZNDX.ORG`, host FQDN) is set in `devenv.nix`.

```bash
secretspec run -- just tag default.my_table   # inject declared secrets for a job
```

## Starting Services

```bash
devenv up             # Start PostgreSQL + Kerberos KDC (+ Atlas, Kudu, Impala on Linux)
```

## ASF submodules and nested devenv

Atlas, Ranger, Kudu, and Impala live under `components/*` as git submodules of
`rch/asf-*` (and similar) forks. **Tracked branch: `rch/devenv`** — the line
non-signals products should consume for Nix/devenv buildability. Optional
`rch/signals` overlays (if any) rebase onto `rch/devenv`; prefer promoting
shared tree fixes into `rch/devenv` instead of product-named branches.

**Build knowledge lives next to those trees**; the host devenv owns **ports,
realm, process graph, and product config**.

| Layer | Responsibility |
|-------|----------------|
| Component on **`rch/devenv`** (`devenv*.nix`) | How to compile that ASF tree on Nix (packages, `*:build-*` tasks) |
| Host (repo-root `devenv.nix`) | PG `:5455`, KDC, Atlas `:21010`, wiring, SecretSpec |
| Product config (`config/`) | `install.properties`, Impala HMS-free, AGE JDBC, local overrides |

**Kudu** already ships a full nested devenv on `rch/devenv`. Treat that as the
reference: split a **library module** (packages + build tasks) from optional
**standalone** processes so hosts can import without starting a second KDC/cluster.

**Maven isolation:** do not install SNAPSHOTs into `~/.m2`. devenv sets
`SIG_MAVEN_REPO=$PWD/.devenv/m2` and `MAVEN_ARGS=-Dmaven.repo.local=…`. Ranger →
Impala FE resolution uses that store; Impala skips the CDP Ranger admin tarball
via `config/impala/impala-config-local.sh` (`RANGER_VERSION_OVERRIDE` /
`RANGER_HOME_OVERRIDE`).

**JDK isolation:** Ranger builds use devenv `jdk11` (Nashorn); Kudu Java/Gradle
uses devenv `jdk17`. Prefer `${pkgs.jdkN}` in tasks over scanning `/nix/store`
or `/usr/lib/jvm`.

**Impala toolchain isolation:** do not add `pkgs.thrift` or `pkgs.boost` to host
`packages` — they leak into CMake and pull the wrong thrift. Impala uses its
downloaded toolchain; only `impala_fdw:build` pins Nix thrift/boost for the FDW.

Design detail and phased rollout:
[`docs/scratch/2026-08-05/234317_asf-devenv-nesting.md`](../../../scratch/2026-08-05/234317_asf-devenv-nesting.md)
(and devenv’s [monorepo guide](https://devenv.sh/guides/monorepo/)).

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
