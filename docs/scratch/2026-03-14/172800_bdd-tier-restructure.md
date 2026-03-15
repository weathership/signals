# BDD Tier Restructure — Component Health + Cross-Component Integration

## Summary

Restructured the BDD test suite from a single `services.feature` with `NotImplementedError` stubs into a proper tier system with fully implemented health checks and TDD integration tests.

## `devenv test` Results

```
4 features passed, 1 failed, 1 error, 9 skipped
13 scenarios passed, 2 failed, 1 error, 37 skipped
42 steps passed, 2 failed, 1 error, 191 skipped
```

**Tier-0 health (15 scenarios):**
- Kerberos: 3/3 pass
- PostgreSQL: 3/3 pass
- Kudu: 3/3 pass
- Impala: 3/3 pass
- Atlas: 1/3 pass (types + search fail — AGE backend limitation)

**Pre-existing:** `agent/extension.feature` tagged `@tier-0` but all steps are `NotImplementedError`

## Changes

### New Files (10)
| File | Purpose |
|------|---------|
| `features/platform/steps/helpers.py` | Shared connection helpers (PG, Impala, Atlas, Kudu, KDC) |
| `features/platform/health_kerberos.feature` | Tier-0: KDC health (3 scenarios) |
| `features/platform/health_postgres.feature` | Tier-0: PG + extensions (3 scenarios) |
| `features/platform/health_atlas.feature` | Tier-0: Atlas REST API (3 scenarios) |
| `features/platform/health_kudu.feature` | Tier-0: Kudu master/tserver (3 scenarios) |
| `features/platform/health_impala.feature` | Tier-0: Impala query engine (3 scenarios) |
| `features/platform/integration_catalog_sync.feature` | Tier-1: Cross-component catalog (4 scenarios) |
| `features/platform/integration_meta_tagging.feature` | Tier-1: Atlas classifications (4 scenarios, all TDD) |
| `features/platform/steps/health_steps.py` | All tier-0 step implementations |
| `features/platform/steps/integration_steps.py` | All tier-1 step implementations |

### Modified Files (4)
| File | Change |
|------|--------|
| `features/environment.py` | Rewritten — `before_all` asserts process + application readiness |
| `features/steps/steps.py` | Updated imports for new step modules |
| `pyproject.toml` | Added `requests>=2.31` dev dependency |
| `devenv.nix` | Extensions in `initialSQL` per-db; enterTest runs tier-0 then tier-1; removed preflight |

### Deleted Files (2)
| File | Reason |
|------|--------|
| `features/platform/services.feature` | Replaced by specific health features |
| `features/platform/steps/service_steps.py` | Replaced by health_steps + integration_steps |

## Bugs Fixed During Testing

1. **pg_cron not in signals db**: `initialScript` runs against `postgres` db. Moved to `initialSQL` on the `signals` database entry in `initialDatabases`.
2. **Thrift PY_SSIZE_T_CLEAN**: Python 3.12 + thrift C accelerator crash. Fixed by blocking `fastbinary`/`fastproto` modules before importing impyla.
3. **Kudu tserver API**: `/api/v1/tablet-servers` doesn't exist. Switched to `/dump-entities` JSON endpoint.
4. **Response status falsy check**: `requests.Response` with 4xx/5xx is falsy; `or` skipped it. Fixed to use `is not None`.
5. **Preflight race**: `devenv test` starts processes before `enterTest` runs, so preflight saw its own ports as conflicts. Removed preflight from enterTest.

## Real Issues Found

1. **Atlas AGE backend: 0 type definitions** — `AgeGraphDBMigrator` is no-op, types aren't stored in graph. The `/types/typedefs/headers` endpoint returns an empty list.
2. **Atlas AGE backend: search 500** — Search endpoint (Solr-based) not functional with AGE backend.

## Design Decisions

- **No silent skips**: `environment.py` asserts in `before_all` if stack unhealthy. ALL scenarios require full stack.
- **Two-phase readiness**: Process-compose probes (process alive) then application checks (Atlas ACTIVE, Impala accepts SQL) with 120s retry.
- **TDD approach**: Tier-1 integration tests tagged `@tdd` fail with clear messages.
- **Shared helpers**: Connection helpers in `helpers.py` — PG, Impala, Atlas, Kudu, KDC.
