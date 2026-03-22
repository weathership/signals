# Quick Start

## Prerequisites

- [devenv](https://devenv.sh/) with Nix
- [direnv](https://direnv.net/) (recommended)

## Setup

```bash
# Clone with submodules
git clone --recurse-submodules git@github.com:cldr-research/signals-360.git
cd signals-360

# Enter development environment
devenv shell

# Pre-cache embedding model (once — required for air-gap operation)
just cache-models

# Start services (PostgreSQL, Kerberos KDC, Kudu, Impala, Atlas)
devenv up
```

## Verify Services

```bash
# PostgreSQL
psql -d signals -c "SELECT extname FROM pg_extension;"

# Kerberos
kinit signals    # password: signals
klist

# Run tier-1 health checks (requires devenv up)
uv run behave features/platform/health_postgres.feature --no-capture
```

## Run BDD Scenarios

```bash
# Tier-0: Classification pipeline (no infrastructure needed)
uv run behave features/classification/ --no-capture

# Tier-1: Health + integration (requires devenv up)
uv run behave features/platform/ features/tagging/ --no-capture

# All tiers
uv run behave --no-capture

# Run unit tests
uv run pytest tests/sigint/ -v
```

## Run the Tagging Pipeline

```bash
# Dry-run: classify columns without writing to Atlas
just tag-dry-run default.my_table

# Live: classify and write SIGDG tags to Atlas
just tag default.my_table
```

## Build Documentation

```bash
devenv tasks run docs:build          # Build mdbook
devenv tasks run docs:serve          # Serve with live reload
```

## Next Steps

- [Scenarios Overview](./scenarios/overview.md) — active and backlog BDD domains
- [Test Infrastructure](./scenarios/testing.md) — tier system, air-gap testing, config-driven BDD
- [Evidence Fusion](./architecture/evidence-fusion.md) — DST belief intervals and mass functions
- [Context Engineering](./architecture/context-engineering.md) — 12 SAGE-ablatable features
- [Metadata Tagging](./architecture/meta-tagging.md) — Tagger pipeline architecture
- [Development Environment](./operations/devenv.md) — full task reference
- [Deployment Modes](./architecture/deployment.md) — laptop, workstation, hybrid, full AWS
