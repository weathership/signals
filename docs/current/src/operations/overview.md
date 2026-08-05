# Operations Guide

Operational procedures for the Signals 360 development and deployment environment.

## Getting Started

1. **[Development Environment](./devenv.md)** — enter the devenv shell, start services, available tasks
2. **[Secrets](./secrets.md)** — SecretSpec declarations, dotenv provider, keytab paths
3. **[Services](./services.md)** — PostgreSQL (AGE, pg_cron) configuration and usage
4. **[Kerberos](./kerberos.md)** — project-local KDC, principals, ticket management (`DEV.VISTA.ZNDX.ORG`)

## Quick Reference

```bash
# Development
devenv shell                         # Enter environment
devenv up                            # Start PostgreSQL + KDC
devenv test                          # Run devenv tests

# Database
psql -d signals                      # Connect to PostgreSQL

# Authentication
kinit signals                        # Get Kerberos ticket (pw: signals)
klist                                # Show current tickets

# Testing
uv run behave                        # Run BDD scenarios
uv run behave --dry-run              # Parse features only

# Documentation
devenv tasks run docs:build          # Build mdbook
devenv tasks run docs:serve          # Serve with live reload
```

## Deployment Operations

For infrastructure provisioning and deployment, see the [Infrastructure](../infrastructure/overview.md) section.
