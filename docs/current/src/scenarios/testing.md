# Test Infrastructure

BDD scenarios are implemented with the [behave](https://behave.readthedocs.io/) framework. Tests are organized into tiers based on what they validate. Tier-0 classification scenarios run offline (no infrastructure). Tier-1 integration scenarios require the full devenv stack (`devenv up`).

## Test Tiers

| Tier | Scope | What It Validates | Infrastructure |
|------|-------|-------------------|----------------|
| **Tier 0** | Classification pipeline | Embedding classification, evidence fusion, feature extraction, taxonomy, config lifecycle, benchmarks | None (offline) |
| **Tier 1** | Component health + integration | Service health, Impala DDL → Kudu, Atlas catalog bridge, meta-tagging pipeline, end-to-end tagging | Full devenv stack |
| **Tier 2** | Engine workflows | gRPC engine, agent-mediated visualization | Engine binary (backlog) |
| **Tier 3** | Full stack | End-to-end with Dask/HoloViews visualization pipeline | Engine + Dask + Datashader (backlog) |

## Running Tests

```bash
# ── Tier 0: Classification (no infrastructure needed) ──────────
uv run behave features/classification/ --no-capture

# ── Tier 1: Integration (requires devenv up) ───────────────────
uv run behave features/platform/ features/tagging/ --no-capture

# ── All tiers ──────────────────────────────────────────────────
uv run behave --no-capture

# ── By tag ─────────────────────────────────────────────────────
uv run behave --tags=@tier-0 --no-capture
uv run behave --tags=@tier-1 --no-capture
uv run behave --tags=@health --no-capture
uv run behave --tags=@integration --no-capture

# ── Specific feature ──────────────────────────────────────────
uv run behave features/platform/integration_meta_tagging.feature --no-capture
uv run behave features/classification/evidence_fusion.feature --no-capture

# ── Dry run (parse only) ─────────────────────────────────────
uv run behave --dry-run

# ── Air-gap mode (no external network calls) ─────────────────
HF_HUB_OFFLINE=1 uv run behave --no-capture
```

### Air-Gap Testing

The devenv shell sets `HF_HUB_OFFLINE=1` and preserves host `HF_HOME` / `HF_HUB_CACHE` /
`SENTENCE_TRANSFORMERS_HOME` (lab RAID under `/raid/cache/*`), falling back to
`build/models` only if no shared cache exists. Models must already be on the shared
cache (or cached once via `just cache-models`):

```bash
just cache-models                        # Download model once
# or: devenv tasks run sigint:cache-models

# All subsequent runs are fully offline
uv run behave --no-capture               # Zero external network calls
```

This ensures BDD scenarios validate the same execution path used in air-gap deployments. See [Air-Gap (Zarf)](../infrastructure/zarf.md) for packaging model artifacts into Zarf archives.

## Feature Tags

Features use hierarchical tags for domain, tier, and scope:

```gherkin
@platform @integration @catalog-sync   # Domain tags
@tier-1                                 # Tier tag (controls which scenarios run)
```

Domain tags: `@platform`, `@integration`, `@catalog-sync`, `@meta-tagging`, `@health`, `@classification`, `@tagging`, `@pipeline`

## Scenario Coverage

### Tier 0 — Classification Pipeline (40 scenarios)

| Feature | Scenarios | What It Tests |
|---------|-----------|---------------|
| `embedding_classification.feature` | 7 | Embedding classifier: confidence thresholds, hierarchical output, name-boost, batch consistency |
| `evidence_fusion.feature` | 6 | DST evidence fusion: mass combination, conflict detection, belief intervals, needs-clarification |
| `feature_extraction.feature` | 5 | 12 SAGE-ablatable features: pattern signals, entropy, cardinality, value description |
| `taxonomy_management.feature` | 5 | SIGDG taxonomy: hierarchy loading, sensitivity mapping, category resolution |
| `vocabulary_mapping.feature` | 4 | Vocabulary mapping: custom term→category overrides, conflict resolution |
| `config_lifecycle.feature` | 4 | HOCON config lifecycle: load, resolve, materialize, validate |
| `benchmark_gittables.feature` | 5 | GitTables benchmark: BFO-grounded taxonomy, 122-type evaluation, accuracy metrics |
| `bespoke_dataset.feature` | 4 | Bespoke dataset classification: custom data, ground truth comparison |

### Tier 1 — Component Health (22 scenarios)

| Feature | Scenarios | What It Tests |
|---------|-----------|---------------|
| `health_postgres.feature` | 3 | PostgreSQL connection, AGE + pg_cron + pg_trgm extensions |
| `health_kerberos.feature` | 3 | KDC ticket granting, keytab validation, principal listing |
| `health_kudu.feature` | 3 | Kudu master API, tablet servers, table creation |
| `health_impala.feature` | 3 | Impala SQL round-trip, DDL, data types |
| `health_atlas.feature` | 10 | Atlas REST API, bootstrap types, entity CRUD, classifications, FTS, suggestions, glossary, lineage |

### Tier 1 — Cross-Component Integration (12 scenarios)

| Feature | Scenarios | What It Tests |
|---------|-----------|---------------|
| `integration_catalog_sync.feature` | 4 | Impala DDL → Kudu storage, Atlas catalog bridge, entity lifecycle |
| `integration_meta_tagging.feature` | 6 | SIGDG type setup, table/column tagging, classification search, Tagger dry-run |
| `pipeline_tagging.feature` | 2 | Full Tagger pipeline (live + dry-run) against Impala tables |

**Catalog sync scenarios:**
1. Impala CREATE TABLE registers in Kudu
2. Impala CRUD operations work end-to-end on Kudu
3. Atlas discovers Impala-managed Kudu tables (via catalog bridge)
4. Atlas entity lifecycle follows Impala DDL (create → register → delete)

**Meta-tagging scenarios:**
5. Tagger creates SIGDG classification types in Atlas
6. Tagger classifies columns and applies tags (live mode)
7. Tagger classifies columns without writing (dry-run mode)
8. Apply classification to a specific column (column-level tagging)
9. Search for entities by classification
10. Tagger setup + dry-run pipeline validates without Atlas writes

**Pipeline tagging scenarios:**
11. Full Tagger pipeline: sample → classify → tag on a live Impala/Kudu table
12. Dry-run pipeline: classify without Atlas writes, verify report output

### Planned — Data Lifecycle (not yet passing)

| Feature | Scenarios | What It Tests |
|---------|-----------|---------------|
| `data_lifecycle.feature` | 5 | Hot→warm Kudu→Iceberg via CTAS, transparent cross-tier queries |

### Total

| Tier | Scenarios | Features |
|------|-----------|----------|
| Tier 0 — Classification | 40 | 8 features |
| Tier 1 — Health | 22 | 5 health features |
| Tier 1 — Integration | 12 | 3 integration features |
| **Total (passing)** | **74** | **16 features** |
| Planned (data lifecycle) | 5 | 1 feature |

## Feature Organization

```
features/
├── environment.py                              # Stack health + cleanup hooks
├── conftest.py                                 # Pytest bridge (optional)
├── classification/                             # Tier-0: offline classification tests
│   ├── steps/
│   │   └── classification_steps.py             # All classification step definitions
│   ├── benchmark_gittables.feature
│   ├── bespoke_dataset.feature
│   ├── config_lifecycle.feature
│   ├── embedding_classification.feature
│   ├── evidence_fusion.feature
│   ├── feature_extraction.feature
│   ├── taxonomy_management.feature
│   └── vocabulary_mapping.feature
├── platform/                                   # Tier-1: health + integration
│   ├── steps/
│   │   ├── __init__.py                         # Cross-domain: imports tagging steps
│   │   ├── helpers.py                          # Connections, Atlas API, catalog bridge
│   │   ├── health_steps.py                     # Health check steps (idempotent)
│   │   └── integration_steps.py                # Catalog sync + meta-tagging steps
│   ├── health_atlas.feature
│   ├── health_impala.feature
│   ├── health_kerberos.feature
│   ├── health_kudu.feature
│   ├── health_postgres.feature
│   ├── integration_catalog_sync.feature
│   ├── integration_meta_tagging.feature
│   └── data_lifecycle.feature                  # Planned: Kudu→Iceberg lifecycle
├── tagging/                                    # Tier-1: end-to-end tagging pipeline
│   ├── steps/
│   │   ├── __init__.py                         # Cross-domain: imports integration steps
│   │   └── tagging_steps.py                    # Pipeline tagging steps
│   └── pipeline_tagging.feature
└── steps/
    └── steps.py                                # Re-exports for behave discovery
```

### Cross-Domain Step Discovery

Behave discovers step definitions from the feature file's parent `steps/` directory. When a feature in `features/platform/` uses steps defined in `features/tagging/steps/`, behave won't find them automatically.

Each domain's `steps/__init__.py` imports steps from sibling domains:
- `features/platform/steps/__init__.py` → imports `features.tagging.steps.tagging_steps`
- `features/tagging/steps/__init__.py` → imports `features.platform.steps.integration_steps`

This ensures steps are discoverable regardless of which domain's feature file is being run.

### Config-Driven BDD

All integration step helpers (`features/platform/steps/helpers.py`) load connection parameters from the HOCON config (`config/base.conf`) via `sigint.config.load_config()`. This ensures BDD tests use the same configuration as the application code — no hardcoded hosts, ports, or credentials that could drift.

```python
from sigint.config import load_config

_CFG = load_config()          # HOCON base.conf + env var overrides

def impala_conn():
    return impala_connect(host=_CFG.impala_host, port=_CFG.impala_port, ...)

def atlas_api(path, method="GET", **kwargs):
    url = f"{_CFG.atlas_url}/api/atlas/v2{path}"
    auth = (_CFG.atlas_user, _CFG.atlas_password)
    ...
```

## Catalog Bridge

The tier-1 integration tests use a Python catalog bridge function (`register_impala_table_in_atlas` in `helpers.py`) that registers Impala-managed Kudu tables in Atlas without requiring Kafka or the Atlas hook infrastructure:

1. Runs `DESCRIBE {table}` on Impala to get column metadata
2. Builds **`rdbms_*`** entities with temporary GUIDs (Atlas `2000-RDBMS` model, Aegir-aligned)
3. POSTs to Atlas `POST /v2/entity/bulk` — single atomic call
4. Atlas resolves `rdbms_table_columns` COMPOSITION and assigns real GUIDs

This validates the Atlas entity contract for governed Kudu tables and enables classification and search tests without Java hook changes.

### qualifiedName Convention

| Entity Type | Pattern | Example |
|-------------|---------|---------|
| `rdbms_instance` | `instance@{cluster}` | `instance@signals` |
| `rdbms_db` | `{db}@{cluster}` | `integration_test@signals` |
| `rdbms_table` | `{db}.{table}@{cluster}` | `integration_test.orders@signals` |
| `rdbms_column` | `{db}.{table}.{col}@{cluster}` | `integration_test.orders.email@signals` |

> Product registration uses **`rdbms_*` only** (not `hive_*`). Physical Kudu names remain separate (`kudu_table` FDW option / `impala::db.table`). See [Roadmap: Entity Type Evolution](../reference/roadmap.md#entity-type-evolution).

## After-Scenario Cleanup

`environment.py` runs best-effort cleanup after each scenario:

- Deletes Atlas entities created by bridge registration (columns first, then table)
- Deletes Atlas entities tagged during classification tests
- Drops Impala tables created during the scenario

Health check steps are idempotent — they verify resources exist rather than requiring a clean state. This allows health scenarios to pass on repeated runs without cleanup.

## Unit Tests

In addition to BDD scenarios, the `sigint` package has comprehensive pytest coverage:

```bash
uv run pytest tests/sigint/ -v          # 363 tests
```

These test individual modules (features, belief, mass functions, config, classifier, etc.) in isolation. The BDD scenarios validate end-to-end behavior across the full stack.
