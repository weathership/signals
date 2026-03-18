# Metadata Tagging

Signals 360 uses Apache Atlas as a metadata catalog and an external AI/ML service to automatically classify table and column names against a BFO-grounded data governance ontology. The goal is to make every table and column in the platform discoverable, consistently labeled, and annotated with formal sensitivity and governance metadata.

## Architecture

```d2
direction: right

impala: Impala {
  tooltip: "SQL engine\nCreates Kudu + Iceberg tables"
}

atlas: Atlas {
  tooltip: "Metadata catalog\nPort 21000"
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

The classification model uses a [context engineering](./context-engineering.md) approach — each column is represented as a structured feature vector that can be measured and optimized using SAGE feature importance analysis.

## Atlas Integration

Atlas provides the metadata catalog that makes Impala tables and columns visible as governed entities:

- **Entity types**: `hive_table`, `hive_column`, `hive_db` (interim — see [Roadmap](../reference/roadmap.md#entity-type-evolution))
- **Classifications**: Applied as Atlas tags using SIGDG CURIEs (e.g., `SIGDG_0025_ContactInformation`)
- **Lineage**: Atlas tracks table-level lineage from INSERT...SELECT and CTAS operations
- **AGE graph queries**: Atlas metadata stored in PostgreSQL with AGE enables graph traversal of classification relationships, lineage paths, and impact analysis

### Atlas + Ranger Policy Flow

Once entities are tagged in Atlas:

1. Ranger policies reference SIGDG classifications (e.g., "mask all columns tagged `SIGDG:0022 PaymentInformation`")
2. Impala enforces Ranger policies at query time
3. The result: automated column masking, row filtering, and access control driven by ontology-grounded metadata tags

## Near-Term Plan

1. **Atlas catalog bridge** (interim; hook/event-driven in future): Register Impala tables in Atlas when created via HMS-free DDL
2. **Tagging service prototype**: Python service that reads Atlas entities and classifies against SIGDG ontology
3. **OWL formalization**: Publish SIGDG as OWL ontology with BFO imports, verify via RASE 5-gate pipeline
4. **Ranger tag-based policies**: Column masking and access control driven by Atlas SIGDG classifications
5. **Feedback loop**: Analyst corrections to classifications improve the model over time
