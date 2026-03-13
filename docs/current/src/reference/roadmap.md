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

### Infrastructure (complete)

- devenv environment with PostgreSQL (AGE, pg_cron), Kerberos KDC
- HMS, Polaris, Kudu processes defined in devenv.nix
- Atlas with AGE backend (replacing JanusGraph/HBase/Solr)
- 7 ASF component submodules on `rch/signals` branches
- BDD feature specifications for all 6 scenarios
- CI workflow for catalog unit + integration tests
- mdbook documentation with GitHub Pages deployment

## Near-Term Objectives

### 1. Iceberg REST Catalog (via Polaris)

Add warm-tier storage to the query stack:

- [ ] End-to-end Iceberg table creation through Polaris REST catalog
- [ ] SELECT queries on Iceberg tables via Impala
- [ ] Kudu → Iceberg data migration via CTAS
- [ ] Validated hot/warm data lifecycle

The `IcebergRESTCatalog` class already implements `createTable`, `dropTable`, and `renameTable` against the Polaris API. The remaining work is integration testing with a running Polaris instance.

### 2. Atlas Metadata Integration

Make Impala tables visible in the Atlas catalog:

- [ ] Register Impala tables/columns in Atlas when created via HMS-free DDL
- [ ] Atlas entity types: `impala_db`, `impala_table`, `impala_column`
- [ ] Lineage tracking for INSERT...SELECT and CTAS operations
- [ ] Verify Atlas web UI shows table metadata (port 21000)

### 3. AI/ML Metadata Tagging

Automatic classification of table and column names using the SIGDG ontology (BFO-grounded data governance vocabulary):

- [ ] Tagging service prototype (Python) that watches Atlas for new entities
- [ ] Classification model trained on the SIGDG information entity hierarchy (SIGDG:0010–0060)
- [ ] Sensitivity levels assigned as BFO qualities (Public → Internal → Confidential → Restricted)
- [ ] Training data: 6 categories (identity, personal, business, system, transaction, metadata)
- [ ] Write classifications back to Atlas as SIGDG tags
- [ ] OWL formalization of SIGDG with BFO 2020 imports

See [Metadata Tagging](../architecture/meta-tagging.md) for the full SIGDG ontology and BFO grounding.

### 4. Ranger Tag-Based Policies

Connect Atlas classifications to query-time enforcement:

- [ ] Ranger policies reference Atlas classification tags
- [ ] Automatic column masking for PII-tagged columns
- [ ] Row-level filtering based on data subject classification
- [ ] Audit logging of access to classified data

## Scenario Tiers

Scenarios are organized by implementation tier:

| Tier | Focus | Prerequisites |
|------|-------|---------------|
| **Tier 0** | Extension packaging, devenv validation | None |
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
