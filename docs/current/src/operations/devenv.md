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

```bash
devenv tasks run signals:kdc-init    # Initialize KDC
devenv tasks run signals:kdc-reset   # Reset KDC database
devenv tasks run docs:build          # Build documentation
devenv tasks run docs:serve          # Serve docs with live reload
```
