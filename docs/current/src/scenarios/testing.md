# Test Infrastructure

BDD scenarios are implemented with the [behave](https://behave.readthedocs.io/) framework. Tests are organized into tiers based on what they validate, and all tiers require the full devenv stack (`devenv up`).

## Test Tiers

| Tier | Scope | What It Validates |
|------|-------|-------------------|
| **Tier 0** | Component health | Individual services respond (PostgreSQL, Atlas API, Kudu master, Impala SQL, Kerberos KDC) |
| **Tier 1** | Cross-component integration | Impala DDL → Kudu storage, Atlas catalog bridge, classification CRUD, column-level tagging |
| **Tier 2** | Engine workflows | gRPC engine, agent-mediated visualization (not yet implemented) |
| **Tier 3** | Full stack | End-to-end with Dask/HoloViews visualization pipeline (not yet implemented) |

All tests require the full devenv stack. There is no offline mode — `before_all` in `environment.py` asserts process-compose health and application-level readiness (Atlas API ACTIVE, Impala accepts SQL) before any scenario runs.

## Running Tests

```bash
# Start the stack first
devenv up

# Run tier-0 health checks
uv run behave features/ --tags=@tier-0 --no-capture

# Run tier-1 integration tests
uv run behave features/ --tags=@tier-1 --no-capture

# Run both tiers
uv run behave features/ --tags=@tier-0,@tier-1 --no-capture

# Run a specific feature
uv run behave features/platform/integration_meta_tagging.feature --no-capture

# Run by domain
uv run behave features/platform/ --no-capture

# Dry run (parse only, no execution)
uv run behave --dry-run
```

## Feature Tags

Features use hierarchical tags for domain, tier, and scope:

```gherkin
@platform @integration @catalog-sync   # Domain tags
@tier-1                                 # Tier tag (controls which scenarios run)
```

Domain tags: `@platform`, `@integration`, `@catalog-sync`, `@meta-tagging`, `@health`

## Scenario Coverage

### Tier 0 — Component Health (10 scenarios)

| Feature | Scenarios | What It Tests |
|---------|-----------|---------------|
| `health_atlas.feature` | 3 | Atlas REST API, type definitions, bootstrap types |
| `health_kerberos.feature` | 2 | KDC ticket granting, keytab validation |
| `health_postgres.feature` | 2 | PostgreSQL connection, AGE + pg_cron extensions |
| `health_kudu_impala.feature` | 3 | Kudu master, tablet servers, Impala SQL round-trip |

### Tier 1 — Cross-Component Integration (8 scenarios)

| Feature | Scenarios | What It Tests |
|---------|-----------|---------------|
| `integration_catalog_sync.feature` | 4 | Impala DDL → Kudu, Atlas catalog bridge registration, entity lifecycle |
| `integration_meta_tagging.feature` | 4 | Classification CRUD, table/column tagging, classification search |

**Catalog sync scenarios:**
1. Impala CREATE TABLE registers in Kudu
2. Impala CRUD operations work end-to-end on Kudu
3. Atlas discovers Impala-managed Kudu tables (via catalog bridge)
4. Atlas entity lifecycle follows Impala DDL (create → register → delete)

**Meta-tagging scenarios:**
5. Create a custom classification type in Atlas
6. Apply classification to an Impala-managed Kudu table
7. Apply classification to a specific column (column-level tagging)
8. Search for entities by classification

### Total

| Tier | Scenarios | Features |
|------|-----------|----------|
| Tier 0 | 10 | 4 health features |
| Tier 1 | 8 | 2 integration features |
| **Total** | **18** | **6 features** |

## Step Definition Structure

Step definitions are organized by scope:

```
features/
├── environment.py                              # Stack health + cleanup hooks
├── platform/
│   ├── steps/
│   │   ├── helpers.py                          # Shared: connections, Atlas API, catalog bridge
│   │   ├── health_steps.py                     # Tier-0: all health check steps
│   │   └── integration_steps.py                # Tier-1: catalog sync + meta-tagging steps
│   ├── health_atlas.feature
│   ├── health_kerberos.feature
│   ├── health_postgres.feature
│   ├── health_kudu_impala.feature
│   ├── integration_catalog_sync.feature
│   └── integration_meta_tagging.feature
├── agent/                                      # Agent scenarios (not yet implemented)
└── analytics/                                  # Analytics scenarios (not yet implemented)
```

## Catalog Bridge

The tier-1 integration tests use a Python catalog bridge function (`register_impala_table_in_atlas` in `helpers.py`) that registers Impala-managed Kudu tables in Atlas without requiring Kafka or the Atlas hook infrastructure:

1. Runs `DESCRIBE {table}` on Impala to get column metadata
2. Builds `hive_db`, `hive_table`, and `hive_column` entities with temporary GUIDs
3. POSTs to Atlas `POST /v2/entity/bulk` — single atomic call
4. Atlas resolves the `hive_table_columns` COMPOSITION relationship and assigns real GUIDs

This validates the Atlas entity contract for Impala-style entities and enables classification and search tests without Java hook changes.

### qualifiedName Convention

| Entity Type | Pattern | Example |
|-------------|---------|---------|
| `hive_db` | `{db}@{cluster}` | `integration_test@signals` |
| `hive_table` | `{db}.{table}@{cluster}` | `integration_test.orders@signals` |
| `hive_column` | `{db}.{table}.{col}@{cluster}` | `integration_test.orders.email@signals` |

> The `hive_*` entity types are an interim convenience — see [Roadmap: Entity Type Evolution](../reference/roadmap.md#entity-type-evolution) for the planned migration to native Impala/Kudu/Iceberg types.

## After-Scenario Cleanup

`environment.py` runs best-effort cleanup after each scenario:

- Deletes Atlas entities created by bridge registration (columns first, then table)
- Deletes Atlas entities tagged during classification tests
- Drops Impala tables created during the scenario

This ensures scenarios are idempotent and can be re-run without manual cleanup.
