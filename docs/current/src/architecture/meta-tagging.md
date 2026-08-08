# Metadata Tagging

Signals 360 uses Apache Atlas as a metadata catalog and an external AI/ML service to automatically classify table and column names against a BFO-grounded data governance ontology. The goal is to make every table and column in the platform discoverable, consistently labeled, and annotated with formal sensitivity and governance metadata.

## Architecture

```d2
direction: right

impala: Impala {
  tooltip: "SQL engine\nCreates Kudu + Iceberg tables"
}

atlas: Atlas {
  tooltip: "Metadata catalog\nPort 21010"
  types: Type System {tooltip: "Entity types, classifications"}
  entities: Entities {tooltip: "Tables, columns, databases"}
  tags: Classifications {tooltip: "BFO-grounded governance tags"}
}

tagger: Tagging Service {
  tooltip: "AI/ML classifier\nAnnotates entities with SIGDG ontology"
  model: Classification Model
  vocab: "SIGDG Ontology\n(BFO-grounded)"
}

pg: PostgreSQL + AGE {
  tooltip: "Graph queries on metadata relationships"
}

impala -> atlas: "Catalog bridge:\ntable/column entities"
atlas.entities -> tagger: "New/changed entities"
tagger -> atlas.tags: "Apply classifications"
atlas -> pg: "Lineage + classification\ngraph queries"
```

## How It Works

1. **Tables created in Impala** become visible in Atlas as entities with columns, types, and ownership metadata.

2. **The tagging service watches Atlas** for new or changed entities (tables, columns). When a new table appears, the service reads its name, column names, column types, and any existing metadata.

3. **The classification model** maps each name to the [SIGDG ontology](../reference/sigdg-ontology.md), assigning both a semantic category and a sensitivity quality. For example:
   - Column `email` → `SIGDG:0025 ContactInformation` with `SIGDG:1030 Confidential`
   - Column `ssn` → `SIGDG:0011 GovernmentIdentifier` with `SIGDG:1040 Restricted`
   - Column `total_amount` → `SIGDG:0021 FinancialInformation` with `SIGDG:1020 Internal`
   - Table `transactions` → `SIGDG:0050 TransactionInformation`

4. **Classifications are written back to Atlas** as tags on the entity, making them visible in the catalog UI and available for policy enforcement via Ranger.

The classification model uses a [context engineering](./context-engineering.md) approach — each column is represented as a structured feature vector that can be measured and optimized using SAGE feature importance analysis. The pipeline outputs Dempster-Shafer belief intervals at every hierarchy level via the [evidence fusion](./evidence-fusion.md) layer.

## Atlas Integration

Atlas provides the metadata catalog that makes Impala-managed Kudu tables and columns visible as governed entities:

- **Entity types**: `rdbms_table`, `rdbms_column`, `rdbms_db`, `rdbms_instance` — Atlas stock RDBMS model (`2000-RDBMS`), same family as Aegir (catalog bridge cut over from interim `hive_*`)
- **Classifications**: Applied as Atlas tags using SIGDG CURIEs (e.g., `SIGDG_0025_ContactInformation`)
- **Lineage**: Atlas tracks table-level lineage from INSERT...SELECT and CTAS operations
- **AGE graph queries**: Atlas metadata stored in PostgreSQL with AGE enables graph traversal of classification relationships, lineage paths, and impact analysis

### Atlas + Ranger Policy Flow

Once entities are tagged in Atlas:

1. Ranger policies reference SIGDG classifications (e.g., "mask all columns tagged `SIGDG:0022 PaymentInformation`")
2. Impala enforces Ranger policies at query time
3. The result: automated column masking, row filtering, and access control driven by ontology-grounded metadata tags

## Validated Pipeline

The end-to-end tagging pipeline has been implemented and validated with 8 BDD scenarios (6 meta-tagging + 2 pipeline tagging):

1. **Atlas catalog bridge** — Python function registers Impala-managed Kudu tables in Atlas via REST API. Validated by 4 catalog sync scenarios.
2. **Tagger service** — `Tagger` class (`src/sigint/tagger.py`) orchestrates sample → classify → tag:
   - `ImpalaSampler` reads column names, types, and sample values from Impala
   - `EmbeddingClassifier` classifies against the SIGDG taxonomy using sentence-transformer embeddings
   - `AtlasClient` writes classifications back as SIGDG tags with confidence scores and evidence
3. **Air-gap isolation** — Shared HF caches (`HF_HOME` / `HF_HUB_CACHE` / `SENTENCE_TRANSFORMERS_HOME`, lab RAID), `HF_HUB_OFFLINE=1`, zero external network calls. See [Air-Gap (Zarf)](../infrastructure/zarf.md#ml-model-artifacts).
4. **HOCON config** — Single source of truth (`config/base.conf`) drives both application code and BDD test helpers. All connection parameters (Impala host/port, Atlas URL/credentials, model cache) flow from config.

### Running the Pipeline

```bash
# Pre-cache model (once)
just cache-models

# Dry-run: classify without writing to Atlas
just tag-dry-run default.my_table

# Live: classify and write SIGDG tags to Atlas
just tag default.my_table

# Or via Python module
uv run python -m sigint --tables default.my_table --dry-run
```

## Next Steps

1. **Event-driven tagging**: Watch Atlas for new entities and trigger classification automatically (replace manual `just tag` invocation)
2. **Evidence fusion calibration**: Calibrate DST discount factors and mass constants against held-out data; resolve source independence assumption (see [Research Roadmap](../reference/research-roadmap.md))
3. **OWL formalization**: Publish SIGDG as OWL ontology with BFO imports, verify via RASE 5-gate pipeline
4. **Ranger tag-based policies**: Column masking and access control driven by Atlas SIGDG classifications
5. **Feedback loop**: Analyst corrections to classifications improve the model over time
6. **Data lifecycle integration**: Preserve classifications across Kudu→Iceberg CTAS migrations
