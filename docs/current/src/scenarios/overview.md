# Scenarios Overview

BDD scenarios (behave) cover the hub and the in-tree classification
pipeline. Active domains have passing coverage; backlog domains
document later work.

## Active Domains

### Classification Pipeline (Tier 0 — 40 scenarios)

Offline tests that validate the sigint classification engine without infrastructure dependencies:

| Feature | File | Scenarios | Description |
|---------|------|-----------|-------------|
| Embedding Classification | `classification/embedding_classification.feature` | 7 | Confidence thresholds, hierarchical output, name-boost |
| Evidence Fusion | `classification/evidence_fusion.feature` | 6 | DST mass combination, conflict detection, belief intervals |
| Feature Extraction | `classification/feature_extraction.feature` | 5 | 12 SAGE-ablatable features, pattern signals |
| Taxonomy Management | `classification/taxonomy_management.feature` | 5 | SIGDG hierarchy, sensitivity mapping |
| Vocabulary Mapping | `classification/vocabulary_mapping.feature` | 4 | Custom term→category overrides |
| Config Lifecycle | `classification/config_lifecycle.feature` | 4 | HOCON config load, resolve, materialize, validate |
| GitTables Benchmark | `classification/benchmark_gittables.feature` | 5 | BFO-grounded 122-type evaluation |
| Bespoke Dataset | `classification/bespoke_dataset.feature` | 4 | Custom dataset classification |

### Platform Health (Tier 1 — 22 scenarios)

Infrastructure health checks that validate each service in the devenv stack:

| Feature | File | Scenarios | Description |
|---------|------|-----------|-------------|
| PostgreSQL | `platform/health_postgres.feature` | 3 | Connection, AGE + pg_cron + pg_trgm extensions |
| Kerberos | `platform/health_kerberos.feature` | 3 | KDC ticket granting, keytab validation |
| Kudu | `platform/health_kudu.feature` | 3 | Master API, tablet servers, table creation |
| Impala | `platform/health_impala.feature` | 3 | SQL round-trip, DDL, data types |
| Atlas | `platform/health_atlas.feature` | 10 | REST API, bootstrap types, entity CRUD, classifications, FTS, suggestions, glossary, lineage |

### Integration & Tagging (Tier 1 — 12 scenarios)

Cross-component integration validating the Impala→Kudu→Atlas→sigint pipeline:

| Feature | File | Scenarios | Description |
|---------|------|-----------|-------------|
| Catalog Sync | `platform/integration_catalog_sync.feature` | 4 | Impala DDL → Kudu, Atlas catalog bridge |
| Meta-Tagging | `platform/integration_meta_tagging.feature` | 6 | SIGDG type setup, column tagging, classification search |
| Pipeline Tagging | `tagging/pipeline_tagging.feature` | 2 | Full Tagger pipeline: sample → classify → tag |

## Planned Enhancement

### Data Lifecycle (Tier 1 — 5 scenarios, not yet passing)

| Feature | File | Scenarios | Description |
|---------|------|-----------|-------------|
| Data Lifecycle | `platform/data_lifecycle.feature` | 5 | Hot→warm Kudu→Iceberg via CTAS, transparent queries |

The hot→warm data lifecycle is the keystone capability of the stack: Kudu for upsert-heavy hot-tier ingest, Iceberg for warm-tier analytics, and Impala providing transparent queries across both tiers. See [Roadmap](../reference/roadmap.md#1-hotwarm-data-lifecycle-keystone-capability).

## Backlog Domains

The following scenario domains are archived in `features_archive/` as future specifications. They document capabilities that will be revisited once the core platform (query stack, metadata governance, classification pipeline) is fully validated.

### Feature Set A: Agent + Visualization (S01–S03)

| Scenario | Description | Prerequisites |
|----------|-------------|---------------|
| S01: Agent-Mediated Visualization | Interactive exploration through web terminal with resolution autoscaling | gRPC engine, Dask, HoloViews |
| S02: Algorithm Extension | Package, deploy, and invoke custom analysis as platform extensions | gRPC engine, extension registry |
| S03: Agent Self-Improvement | Define performance objectives, iterate toward quantitative improvements | gRPC engine, evaluation harness |

Archived features: `features_archive/agent/visualization.feature`, `extension.feature`, `evolution.feature`

### Feature Set B: Analytics (S04–S06)

| Scenario | Description | Prerequisites |
|----------|-------------|---------------|
| S04: OTel Root Cause Analysis | Correlate degradation signals with infrastructure changes | OTel collector, Dask analytics |
| S05: Cybersecurity Investigation | Investigate malicious behavior using correlated log sources | Security data pipeline |
| S06: Streaming Ontology | Ontology-grounded feature discovery from high-velocity streams | Streaming ingest, ontology service |

Archived features: `features_archive/analytics/otel_investigation.feature`, `cybersec_investigation.feature`, `streaming_ontology.feature`

Also archived: `features_archive/grpc_engine.feature` — gRPC engine health and connectivity checks.

These scenarios remain valid specifications. When the gRPC engine, Dask compute layer, or streaming pipeline is implemented, the corresponding features can be moved from `features_archive/` back to `features/` and connected to step definitions.

## Current Status

| Domain | Scenarios | Status |
|--------|-----------|--------|
| Classification (tier-0) | 40 | All passing |
| Platform health (tier-1) | 22 | All passing |
| Integration + tagging (tier-1) | 12 | All passing |
| **Active total** | **74** | **74/74 passing** |
| Data lifecycle (planned) | 5 | Not yet passing |
| Backlog (S01–S06 + gRPC) | ~29 | Archived |

See [Test Infrastructure](./testing.md) for the tier system, how to run scenarios, and the BDD framework architecture.
