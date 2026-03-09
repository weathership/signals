# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

signals-360 — early-stage project. Licensed Apache 2.0.

## Development Environment

Uses [devenv](https://devenv.sh/) (Nix-based) with direnv for automatic shell activation.

- **Enter the dev shell:** `devenv shell` (or automatic via direnv)
- **Start all services:** `devenv up` (PostgreSQL + Kerberos KDC)
- **Run devenv tests:** `devenv test`

Key files:
- `devenv.nix` — packages, services, processes, tasks, and shell configuration
- `devenv.yaml` — Nix inputs configuration
- `.envrc` — direnv integration
- `scripts/kdc-init.sh` — idempotent KDC initialization script

### Languages
- **Rust** — primary application language
- **Python 3.12** — tooling and Airflow; uv for package management
- **Java 21** — ASF component builds (Maven enabled)
- **TypeScript/JavaScript** — frontend

### ASF Components (submodules in `components/`)

All tracked on `rch/signals` branch from `rch` GitHub forks:

| Component | Purpose |
|-----------|---------|
| `atlas` | Metadata governance and data catalog |
| `ranger` | Authorization and access control |
| `kudu` | Columnar storage engine |
| `impala` | Distributed SQL query engine |
| `iceberg` | Table format for large analytic datasets |
| `airflow` | Workflow orchestration |
| `nifi` | Data flow routing and transformation |

Build dependencies for C++ components (Kudu, Impala): cmake, ninja, gcc, protobuf, flatbuffers.

## Architecture

### gRPC Engine + WASM Terminal

The system provides a web-based interface via a Ghostty WASM terminal component:

- **Ghostty WASM terminal** — browser-embedded terminal (bottom half of web UI)
- **gRPC engine** — server-side agent engine (Rust, inspired by mistral-vibe)
- **HoloViews/Datashader/Dask** — agent-mediated visualization stack (top half of web UI)

Data flow: user instructions transit gRPC from the WASM terminal to the server engine, which directs the Dask/Datashader pipeline to recompute HoloViews visualizations, streamed back to the web client.

WASM tooling: wasmtime, wasm-pack, wasm-bindgen-cli, binaryen.

### Deployment

- **AWS** — opentofu (IaC), ansible (configuration management), awscli2
- **Air-gap** — zarf (disconnected K8s packaging)
- **Kubernetes** — kubectl, helm, tilt (dev), k3d (local), k9s (TUI)
- **Containers** — podman
- **Ingress** — cloudflared (Cloudflare Tunnel)
- **Policy** — conftest (OPA validation)

## Services

### PostgreSQL 16
- **Extensions:** Apache AGE (graph queries), pg_cron (scheduled jobs)
- **Database:** `signals` (created automatically)
- **shared_preload_libraries:** `age,pg_cron`
- Managed by `services.postgres` in devenv — starts automatically with `devenv up`

### Kerberos KDC
- **Realm:** `KRBTEST.COM`
- **KDC port:** `8848` (127.0.0.1)
- **Data directory:** `.devenv/kdc/` (gitignored)
- **Principals:**
  - `postgres/localhost@KRBTEST.COM` — service principal (keytab at `.devenv/kdc/postgres.keytab`)
  - `signals@KRBTEST.COM` — application user (password: `signals`)
- Runs as a devenv process via `devenv up`
- Shell automatically sets `KRB5_CONFIG`, `KRB5_KDC_PROFILE`, `KRB5CCNAME` to project-local paths

### Common Commands
```
devenv up                               # Start PostgreSQL + KDC
devenv tasks run signals:kdc-init       # Initialize/verify KDC
devenv tasks run signals:kdc-reset      # Reset KDC database
devenv tasks run docs:build             # Build mdbook documentation
devenv tasks run docs:serve             # Serve docs with live reload
psql -d signals                         # Connect to database
kinit signals                           # Get Kerberos ticket (pw: signals)
klist                                   # Show current tickets
```

## Build Commands

No build targets exist yet. When Rust source is added:
```
cargo build
cargo test
cargo run
```

## Documentation

mdbook with d2, katex, and mermaid preprocessors.
- Source: `docs/current/src/`
- Config: `docs/current/book.toml`
- Work notes: `docs/scratch/$(date --iso-8601)/` with time-prefixed filenames
