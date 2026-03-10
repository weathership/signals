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

# Start services (PostgreSQL + Kerberos KDC)
devenv up
```

## Verify Services

```bash
# PostgreSQL
psql -d signals -c "SELECT extname FROM pg_extension;"

# Kerberos
kinit signals    # password: signals
klist
```

## Run BDD Scenarios

```bash
# Dry run — verify feature parsing
uv run behave --dry-run

# Run Tier 0 scenarios (no services required)
uv run behave --tags="not @db-required and not @kdc-required and not @engine-required and not @viz-required"

# Run all (skips tiers with missing infrastructure)
uv run behave
```

## Build Documentation

```bash
devenv tasks run docs:build          # Build mdbook
devenv tasks run docs:serve          # Serve with live reload
```

## Next Steps

- [Scenarios Overview](./scenarios/overview.md) — the 6 core scenarios driving development
- [Development Environment](./operations/devenv.md) — full task reference (k8s, aws, docs)
- [Deployment Modes](./architecture/deployment.md) — laptop, workstation, hybrid, full AWS
- [Infrastructure](./infrastructure/overview.md) — OpenTofu, Ansible, Zarf, Tilt, OPA
