# Roadmap

## Current State

### Core Query Stack (complete)

HMS-free Impala + Kudu is operational. The full table lifecycle works without the Hive Metastore, HDFS, or HBase:

- **Impala** built from source (statestore, catalogd, impalad)
- **Kudu** master + tablet server running
- **PostgreSQL** catalog registry replacing HMS for table metadata
- **DDL**: CREATE/DROP DATABASE, CREATE/DROP TABLE
- **DML**: INSERT, SELECT with JOINs, aggregations, subqueries
- **Data types**: INT, STRING, DOUBLE, BOOLEAN, BIGINT

### Atlas Metadata Integration (in progress)

Atlas with the AGE backend is running and the catalog bridge is validated:

- **Atlas AGE backend** operational — PostgreSQL + AGE replacing JanusGraph/HBase/Solr
- **Catalog bridge** — Python function registers Impala-managed Kudu tables in Atlas via REST API
- **Entity CRUD** — `hive_table`, `hive_column`, `hive_db` entities (interim types from Atlas bootstrap)
- **Classification CRUD** — custom classification types, table/column tagging, search by classification
- **BDD coverage** — 74 scenarios across 16 features (40 tier-0 classification + 22 tier-1 health + 12 tier-1 integration), all passing

### Infrastructure (complete)

- devenv environment with PostgreSQL (AGE, pg_cron, pg_trgm), Kerberos KDC
- HMS, Polaris, Kudu processes defined in devenv.nix
- Atlas with AGE backend (replacing JanusGraph/HBase/Solr)
- ASF component submodules on shared **`rch/devenv`** branches (`rch/asf-*`)
- BDD feature specifications across 16 features with tier-0 and tier-1 coverage
- Air-gap isolation (`HF_HUB_OFFLINE=1`, model cache, zero external network calls)
- CI workflow for catalog unit + integration tests
- mdbook documentation with GitHub Pages deployment

## Near-Term Objectives

### 1. Hot/Warm Data Lifecycle (keystone capability)

The core value proposition of the stack: Kudu for upsert-heavy hot-tier ingest, Iceberg for warm-tier storage as upserts taper off, and Impala providing transparent queries across both tiers.

- [ ] End-to-end Iceberg table creation through Polaris REST catalog
- [ ] SELECT queries on Iceberg tables via Impala
- [ ] Kudu → Iceberg data migration via CTAS
- [ ] Lifecycle validation workload (`tests/workload/lifecycle.py`) — hot→warm transition
- [ ] Polaris catalog integration with the catalog registry

The `IcebergRESTCatalog` class already implements `createTable`, `dropTable`, and `renameTable` against the Polaris API. The remaining work is integration testing with a running Polaris instance and validating the full hot→warm lifecycle: data ingested into Kudu, aged via CTAS into Iceberg, queryable transparently through Impala.

### 2. Entity Type Evolution

The tier-1 BDD tests currently use `hive_table`, `hive_column`, and `hive_db` entity types because they ship with Atlas's bootstrap models. This is pragmatic — they provide working entity CRUD, classification, and relationship support out of the box — but entity type names should reflect the actual storage and query engines in the stack.

| Phase | Entity Types | Status |
|-------|-------------|--------|
| Phase 1 (current) | `hive_table`, `hive_column`, `hive_db` | Working — Atlas bootstrap types, validated by 74 BDD scenarios |
| Phase 2 | `impala_table`, `impala_column`, `impala_db` | Planned — custom type model in `addons/models/`, superType DataSet |
| Phase 3 | `kudu_table`, `iceberg_table` alongside `impala_table` | Future — storage-tier-aware types for lineage across hot/warm |

**Why this matters:** Phase 1 validates the Atlas entity contract and classification pipeline. Phase 2 makes entity types match the query engine (Impala, not Hive). Phase 3 enables lineage tracking across the Kudu→Iceberg migration boundary — when a CTAS moves data from hot to warm tier, the lineage should connect a `kudu_table` source to an `iceberg_table` target, both queryable through `impala_table`.

### 3. Atlas-Impala Catalog Bridge

Evolve the catalog bridge from a test helper to a production integration:

- [x] Bridge function registers Impala tables in Atlas via REST API
- [x] Classification CRUD — create types, apply to tables and columns
- [x] Column-level tagging — individual column classification
- [ ] Automated registration — hook or event-driven (replace manual bridge calls)
- [ ] Lineage tracking for INSERT...SELECT and CTAS operations
- [ ] Search-by-classification in AGE backend (full-text search on classification names)

### 4. AI/ML Metadata Tagging

Automatic classification of table and column names using the SIGDG ontology (BFO-grounded data governance vocabulary):

- [x] Classification model trained on the SIGDG information entity hierarchy (SIGDG:0010–0060)
- [x] Training data: 6 categories (identity, personal, business, system, transaction, metadata)
- [x] Sensitivity levels assigned as BFO qualities (Public → Internal → Confidential → Restricted)
- [x] Context engineering pipeline with 12 ablatable features and SAGE importance analysis
- [x] Multi-stage pipeline (feature extraction → classification → run report + SAGE)
- [x] Structured run reports (JSON + parquet) for method/feature comparison
- [x] Tagging service prototype (Python) — `Tagger` class orchestrates sample → classify → tag
- [x] Write classifications back to Atlas as SIGDG tags (via `AtlasClient.apply_classification()`)
- [x] Air-gap isolation — local model cache, `HF_HUB_OFFLINE=1`, zero external calls
- [x] BDD validation — 6 meta-tagging + 2 pipeline scenarios, all passing
- [ ] OWL formalization of SIGDG with BFO 2020 imports
- [ ] Event-driven tagging — watch Atlas for new entities (replace manual invocation)

See [Metadata Tagging](../architecture/meta-tagging.md) for the architecture and [Context Engineering](../architecture/context-engineering.md) for the SAGE-based feature evaluation methodology. The [SIGDG Ontology](./sigdg-ontology.md) reference documents the full BFO-grounded vocabulary.

### 5. Ranger Tag-Based Policies

Connect Atlas classifications to query-time enforcement:

- [ ] Ranger policies reference Atlas classification tags
- [ ] Automatic column masking for PII-tagged columns
- [ ] Row-level filtering based on data subject classification
- [ ] Audit logging of access to classified data

## Scenario Tiers

Scenarios are organized by implementation tier:

| Tier | Focus | Prerequisites |
|------|-------|---------------|
| **Tier 0** | Component health | None |
| **Tier 1** | Query stack, metadata catalog, classification | Impala + Kudu + Atlas |
| **Tier 2** | gRPC engine, extension deployment, self-improvement | Engine binary |
| **Tier 3** | Full visualization pipeline, analytics scenarios | Engine + Dask + Datashader |

## Eliminated Dependencies

The following components are intentionally excluded from the stack:

| Component | Replacement | Reason |
|-----------|-------------|--------|
| Hive Metastore | PG catalog registry + KuduMetaProvider | Eliminate Thrift dependency, simplify deployment |
| HDFS | Local filesystem / S3 | No distributed filesystem needed for Kudu + Iceberg |
| HBase | PostgreSQL + AGE | Atlas backend simplified to single database |
| Solr | PostgreSQL full-text search | Atlas search simplified |
| ZooKeeper | Kudu's built-in Raft consensus | No external coordination service |
| Trino | Impala | Kudu connector removed from Trino 473 |

## Backlog

The following capabilities are documented as BDD feature specifications in `features_archive/` and will be revisited once the core platform is fully validated.

### Agent + Visualization (S01–S03)

- **S01: Agent-Mediated Visualization** — Interactive data exploration through a WASM terminal with resolution autoscaling and multi-persona views. Requires the gRPC engine, Dask distributed compute, and HoloViews/Datashader rendering.
- **S02: Algorithm Extension** — Package, deploy, and invoke custom analysis code as platform extensions through the agent engine.
- **S03: Agent Self-Improvement** — Define performance objectives and iterate toward quantitative improvements via self-directed evaluation cycles.

### Analytics (S04–S06)

- **S04: OTel Root Cause Analysis** — Correlate degradation signals with infrastructure changes for evidence-backed root cause analysis using OpenTelemetry data.
- **S05: Cybersecurity Investigation** — Investigate malicious behavior using correlated log sources and detection logic.
- **S06: Streaming Ontology** — Ontology-grounded feature discovery from high-velocity streams with human-in-the-loop direction.

### gRPC Engine

- gRPC engine health checks, instruction echo, extension registry. Archived from `features/platform/grpc_engine.feature`.

These remain valid specifications. When the gRPC engine or streaming pipeline is implemented, features move from `features_archive/` back to `features/` and are connected to step definitions. See [Scenarios Overview](../scenarios/overview.md) for the full backlog listing
