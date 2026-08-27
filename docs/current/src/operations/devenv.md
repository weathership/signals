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

## Starting Services (turn-key)

```bash
# New machine (one-time): git submodule update --init --recursive
# One-time ASF builds if missing: devenv tasks run kudu:build-cpp && devenv tasks run impala:build

just up                 # devenv up -d — full stack; validates + bootstraps
devenv processes list   # Expect 12: kudu-*, impala-*, atlas, marquez-web, rustfs, signals-ui, …
just down               # processes down + stop *our* Postgres only (lattice-safe)
just stack-reset        # down + free our orphans + up -d
just rebuild            # Polarisfork assemble + devenv restart + wait :8182
just redeploy           # K8s product refresh (Metaflow, Airflow, Eventing → YK queues)
just kinit              # Refresh user ticket if needed
just kerberos-status    # Expect: impala HS2 GSSAPI OK
```

Prefer **`just up` / `just down`** over bare `devenv processes down`: the bare
command often leaves the signals postmaster on **:5455**, which then blocks the
next `up` under `strictPorts`. `just down` only stops **this** tree’s
`.devenv/state/postgres` — never gaius/synth/atelier/system PG.

**`devenv up -d` is the only required runtime command.** It:

1. Ensures data layout under `SIGNALS_DATA_ROOT`
2. Starts **KDC**, then **kerberos-bootstrap** (keytabs + kinit) before Kudu/Impala
3. Starts the full host graph (Postgres, RustFS, Atlas, Marquez-web, Ranger, **Kudu**, **Impala**, signals-ui)
4. Runs **stack-ready** before signals-ui: data-plane health, YuniKorn/Knative, Metaflow, Airflow (auto-deploy when missing). Peers use **`just signals-ready`** for check-only PASS/WARN/FAIL (critical includes Kudu + Metaflow).

`just bootstrap` remains a **recovery alias** for Kerberos outside a process session — not a separate curriculum step.

**Full stack is always required.** Host data/governance services and the RKE2
**critical plane** (YuniKorn, Knative, Metaflow, Airflow) are one Signals
deployment — not optional bolt-ons. See
[Critical plane](../architecture/stack-critical-plane.md).

`devenv.yaml` sets **`strictPorts: true`** so Postgres stays on **:5455** (no silent
bump to :5456 that breaks Impala catalogd / JDBC).

### Postgres port lattice (shared lab host)

Multiple devenv trees share the machine. **Do not reuse each other’s PG ports:**

| Port | Project |
|------|---------|
| 5432 | System/apt PostgreSQL (leave alone) |
| 5438 | cybersec / cyberphy |
| 5444 | gaius |
| **5455** | **signals (this tree)** |
| 5533 | atelier |
| 5555 | aegir |
| 5566 | synth |

`scripts/signals_port_lattice.sh` runs at process start: if **:5455** is held by a
process that is **not** this tree’s postmaster, `devenv up` **fails** with a clear
message — it will **not** kill another project’s Postgres. Stack reset only stops
our `.devenv/state/postgres` postmaster.

Do not run Atlas/Marquez/Metaflow as long-lived orphans outside `devenv up` /
`devenv processes down` (plus RKE2 platform bootstrap).

**Python is devenv's.** `languages.python` (python312 + uv) owns `.devenv/state/venv`;
every script, readiness oneshot and systemd unit resolves the interpreter through
`scripts/signals_python.sh` (`signals_python_path` / `signals_py`, override
`SIGNALS_PYTHON`) — never a host `python3`, which has no protobuf/grpc/kerberos wheels
(the `signals-engine` false WARN in `signals-ready`). Justfile recipes use `uv run`.

Process manager: **native** (`process.manager.implementation = "native"`). Ordering
uses process `after` / `ready` (Kudu → Impala; Postgres → Atlas → Marquez;
**signals:stack-ready** before signals-ui). Control:

```bash
devenv up -d              # start full graph
just stack-ready          # preflight (+ optional auto-bootstrap)
just signals-ready        # check-only oneshot for peers / systemd
devenv processes list     # expect kudu-*, impala-*, atlas, marquez-web, rustfs, signals-ui, …
devenv processes down     # stop full graph (or: just down)
```

| Process / platform | Role | Default port(s) |
|--------------------|------|-----------------|
| `postgres` | devenv PostgreSQL 16 + AGE (Atlas graph, Ranger, catalog). Not pglite. | 5455 |
| `kdc` | Kerberos | 8848 |
| `kudu-master` / `kudu-tserver` | Columnar store | 7051/7050 (web 8051/8050) |
| `impala-statestore` / `catalogd` / `impalad` | SQL + kudu_scan | HS2 21050 |
| `atlas` | Governance + OL API | **21010** |
| `marquez-web` | OL UI → Atlas `/api/v1` | **21011** |
| `ranger-admin` | Authz | 6080 |
| `rustfs` | S3 objects (**critical** object plane) | 9010 |
| `polaris` | Iceberg REST catalog (warehouse on RustFS) | **8181** / admin **8182** |
| `signals-ui` | Control plane UI (requires stack-ready) | **9889** |
| RKE2 **YuniKorn** | Federation scheduler | REST **30080** |
| RKE2 **Knative** | Serving (+ Eventing M3) | Serving ns |
| RKE2 **Metaflow** | Platform metadata service | **30180** |
| RKE2 **Airflow 3** | Platform DAG orchestration + UI (`just airflow-ui`; admin/admin) | **30800** |

**Turn-key first run:** `devenv up [-d]` is the only entry point users need for the
core stack. Marquez-web is bootstrapped like other heavy UI deps (cybersec pattern):

1. `languages.javascript` points at `components/marquez/web` with
   `npm.install.enable = true` (checksummed `npm clean-install` on shell enter).
2. Task `marquez:build-web` has `before = [ "devenv:processes:marquez-web" ]`, so
   process-compose runs submodule init + npm + webpack **before** the UI process.
3. `processes.marquez-web` only serves (`setupProxy.js` → Atlas `/api/v1`).

**Port convention:** Marquez UI binds **Atlas HTTP + 1** (defaults `:21010` /
`:21011`). Override with `MARQUEZ_WEB_PORT` / `SIGNALS_ATLAS_HTTP_PORT`. Do not
use `:3000` for Marquez — leave that for ad-hoc local frontends.

No separate “please run marquez:build-web first” step for a normal lab bring-up.

**Data root:** durable services use `SIGNALS_DATA_ROOT` (lab default
`/raid/signals` — `kudu/`, `rustfs/`, `flink/`, `backups/`). See
[Storage and backup](./storage-and-backup.md). Preserve Atlas/Ranger with
`just backup` / `just restore`.

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
| Host (repo-root `devenv.nix`) | PG `:5455`, KDC, Atlas `:21010`, Marquez-web `:21011` (Atlas + 1), wiring, SecretSpec |
| Product config (`config/`) | `install.properties`, Impala HMS-free, AGE JDBC, local overrides |

**Kudu** already ships a full nested devenv on `rch/devenv`. Treat that as the
reference: split a **library module** (packages + build tasks) from optional
**standalone** processes so hosts can import without starting a second KDC/cluster.

**Maven isolation:** do not install SNAPSHOTs into `~/.m2`. devenv sets
`SIG_MAVEN_REPO=$PWD/.devenv/m2` and `MAVEN_ARGS=-Dmaven.repo.local=…`. Ranger →
Impala FE resolution uses that store; Impala skips the CDP Ranger admin tarball
via `config/impala/impala-config-local.sh` (`RANGER_VERSION_OVERRIDE` /
`RANGER_HOME_OVERRIDE`).

**JDK isolation:** Prefer `${pkgs.jdkN}` in tasks over scanning `/nix/store` or
`/usr/lib/jvm`. Kudu Java/Gradle uses devenv `jdk17`. Ranger **currently** uses
devenv `jdk11` only because of remaining **Nashorn** build deps—that is interim;
when appropriate we move Ranger forward to ditch Nashorn and modern JDKs (see
[Ranger](../components/ranger.md)).

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
