# Test Infrastructure

BDD scenarios are implemented with the [behave](https://behave.readthedocs.io/) framework. A tier system controls which scenarios run based on available infrastructure.

## Test Tiers

| Tier | Name | Requirements | Tags |
|------|------|-------------|------|
| **Tier 0** | Pure | None — code-only tests | (default) |
| **Tier 1** | Services | PostgreSQL, Kerberos KDC | `@db-required`, `@kdc-required` |
| **Tier 2** | Engine | gRPC engine running | `@engine-required` |
| **Tier 3** | Full | Engine + visualization stack + Dask | `@viz-required` |

Each tier includes all lower tiers. A Tier 2 environment can run Tier 0, 1, and 2 scenarios.

## Running Tests

```bash
# Run all scenarios (skips tiers with missing infrastructure)
uv run behave

# Run only Tier 0 (pure) scenarios
uv run behave --tags="not @db-required and not @kdc-required and not @engine-required and not @viz-required"

# Run a specific feature
uv run behave features/agent/visualization.feature

# Run scenarios by domain
uv run behave features/agent/
uv run behave features/analytics/
uv run behave features/platform/

# Dry run (parse only, no execution)
uv run behave --dry-run
```

## Tier Detection

The `features/environment.py` hooks detect the current tier by checking for running services:

- **Tier 1**: Attempts PostgreSQL connection and `kinit` ticket request
- **Tier 2**: Checks for gRPC engine health endpoint
- **Tier 3**: Checks for Dask scheduler and HoloViews availability

Scenarios requiring infrastructure above the detected tier are automatically skipped with an informative message.

## Feature Tags

Features use tags for both domain classification and tier requirements:

```gherkin
@agent @viz                      # Domain: agent, visualization
@tier-2 @engine-required         # Requires Tier 2 (gRPC engine)
@tier-3 @viz-required            # Requires Tier 3 (full stack)
```

## Scenario Coverage by Tier

| Tier | Scenarios | Features |
|------|-----------|----------|
| Tier 0 | 2 | Extension packaging, devenv environment |
| Tier 1 | 3 | PostgreSQL extensions, Kerberos KDC, keytab validation |
| Tier 2 | 7 | Engine connectivity, extension deploy, self-improvement |
| Tier 3 | 17 | Visualization, RCA, cybersec, streaming, persona views |
| **Total** | **29** | **8 features** |

## Step Definition Structure

Step definitions are organized by domain with a re-export module for behave discovery:

```
features/steps/steps.py              # Re-exports all domain steps
features/agent/steps/agent_steps.py  # Visualization, extension, evolution
features/analytics/steps/analytics_steps.py  # OTel, cybersec, streaming
features/platform/steps/service_steps.py     # Platform, gRPC engine
```

All step definitions currently raise `NotImplementedError` — they will be implemented as components are built.
