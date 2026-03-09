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

## Common Tasks

```bash
devenv tasks run signals:kdc-init    # Initialize KDC
devenv tasks run signals:kdc-reset   # Reset KDC database
devenv tasks run docs:build          # Build documentation
devenv tasks run docs:serve          # Serve docs with live reload
```
