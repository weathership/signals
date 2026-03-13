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

impala -> atlas: "Hook: table/column\nmetadata events"
atlas.entities -> tagger: "New/changed entities"
tagger -> atlas.tags: "Apply classifications"
atlas -> pg: "Lineage + classification\ngraph queries"
```

## How It Works

1. **Tables created in Impala** become visible in Atlas as entities with columns, types, and ownership metadata.

2. **The tagging service watches Atlas** for new or changed entities (tables, columns). When a new table appears, the service reads its name, column names, column types, and any existing metadata.

3. **The classification model** maps each name to the SIGDG ontology, assigning both a semantic category and a sensitivity quality. For example:
   - Column `email` → `SIGDG:0025 ContactInformation` with `SIGDG:1030 Confidential`
   - Column `ssn` → `SIGDG:0011 GovernmentIdentifier` with `SIGDG:1040 Restricted`
   - Column `total_amount` → `SIGDG:0021 FinancialInformation` with `SIGDG:1020 Internal`
   - Table `transactions` → `SIGDG:0050 TransactionInformation`

4. **Classifications are written back to Atlas** as tags on the entity, making them visible in the catalog UI and available for policy enforcement via Ranger.

## Data Governance Ontology (SIGDG)

The Signals Data Governance ontology (prefix `SIGDG`) is grounded in BFO 2020 (Basic Formal Ontology). BFO provides the upper-level categories; SIGDG specializes them for data governance.

### BFO Grounding

```
BFO:0000031 generically dependent continuant
  └── SIGDG:0001 InformationEntity         ── "data that can be stored and transferred"

BFO:0000019 quality
  └── SIGDG:1001 SensitivityLevel          ── "inheres in an information entity"

BFO:0000023 role
  └── SIGDG:2001 DataSubjectRole           ── "externally grounded in data governance context"

BFO:0000015 process
  └── SIGDG:3001 DataLifecycleProcess      ── "transformation, migration, classification"
```

BFO's `generically dependent continuant` (GDC) is the natural home for information entities — they depend on some material carrier (disk, memory) but can be copied and transferred between carriers. Sensitivity levels are `qualities` that inhere in information entities. Data subject roles are `roles` played by persons in a governance context.

### CURIE Prefix

```
SIGDG → https://signals360.dev/ontology/dg/
BFO   → http://purl.obolibrary.org/obo/BFO_
```

### Information Entity Hierarchy

```
SIGDG:0001  InformationEntity               (⊑ BFO:0000031)
├── SIGDG:0010  IdentityInformation         "data that identifies a natural or legal person"
│   ├── SIGDG:0011  GovernmentIdentifier    "state-issued ID: passport, SSN, driver's license"
│   ├── SIGDG:0012  PlatformIdentifier      "account-scoped ID: username, email, employee ID"
│   └── SIGDG:0013  DeviceIdentifier        "hardware-bound ID: IMEI, MAC address, UDID"
├── SIGDG:0020  PersonalInformation         "data about a natural person"
│   ├── SIGDG:0021  FinancialInformation    "monetary data: balances, scores, compensation"
│   │   └── SIGDG:0022  PaymentInformation  "payment instruments: card numbers, bank accounts"
│   ├── SIGDG:0023  DemographicInformation  "attributes: age, gender, ethnicity, education"
│   ├── SIGDG:0024  HealthInformation       "medical conditions, biometrics, genetic data"
│   ├── SIGDG:0025  ContactInformation      "addresses, phone numbers, email"
│   └── SIGDG:0026  CredentialInformation   "passwords, PINs, keys, security questions"
├── SIGDG:0030  BusinessInformation         "data about an enterprise"
│   ├── SIGDG:0031  ProprietaryInformation  "trade secrets, technical documentation"
│   └── SIGDG:0032  RegulatoryInformation   "SEC filings, compliance records"
├── SIGDG:0040  SystemInformation           "infrastructure and configuration data"
│   ├── SIGDG:0041  ConfigurationData       "IPs, cluster membership, file paths"
│   └── SIGDG:0042  AccessControlData       "permissions, LDAP groups, session state"
├── SIGDG:0050  TransactionInformation      "event records: orders, sessions, timestamps"
└── SIGDG:0060  TransformationMetadata      "provenance: encryption, masking, hashing records"
```

### Sensitivity Levels

Sensitivity is modeled as a BFO `quality` (`BFO:0000019`) that inheres in an information entity:

| CURIE | Label | Definition |
|-------|-------|------------|
| `SIGDG:1010` | Public | Intended for unrestricted disclosure |
| `SIGDG:1020` | Internal | Not public but no harm if disclosed internally |
| `SIGDG:1030` | Confidential | Disclosure causes measurable harm to individuals or enterprise |
| `SIGDG:1040` | Restricted | Disclosure causes severe harm; regulated by law (GDPR, HIPAA, PCI) |

### Data Subject Roles

Data subjects are modeled as BFO `roles` (`BFO:0000023`), allowing the same information entity to carry different sensitivity depending on whose data it is:

| CURIE | Label | Example |
|-------|-------|---------|
| `SIGDG:2010` | CustomerRole | End-user, subscriber, app developer |
| `SIGDG:2020` | EmployeeRole | Employee, contractor, vendor |
| `SIGDG:2030` | EnterpriseRole | Corporate entity, partner organization |

A column tagged `SIGDG:0025 ContactInformation` with subject `SIGDG:2010 CustomerRole` may be `Restricted`, while the same column with subject `SIGDG:2020 EmployeeRole` may be `Confidential`.

### Data Lifecycle Processes

Classification itself is a BFO `process` (`BFO:0000015`):

| CURIE | Label | Definition |
|-------|-------|------------|
| `SIGDG:3010` | ClassificationProcess | Assigning SIGDG categories to an entity |
| `SIGDG:3020` | MigrationProcess | Moving data between storage tiers |
| `SIGDG:3030` | MaskingProcess | Applying de-identification transforms |

## Training Data

The classification model is trained on synthetic datasets spanning the SIGDG hierarchy:

| Table | SIGDG Category | Columns | Rows |
|-------|----------------|---------|------|
| `identity_data` | SIGDG:0010 IdentityInformation | 59 | 100 |
| `personal_data` | SIGDG:0020 PersonalInformation | 215 | 100 |
| `business_data` | SIGDG:0030 BusinessInformation | 21 | 100 |
| `system_data` | SIGDG:0040 SystemInformation | 43 | 100 |
| `transaction_data` | SIGDG:0050 TransactionInformation | 17 | 100 |
| `metadata_info` | SIGDG:0060 TransformationMetadata | 77 | 100 |
| `annotations` | (ontology reference) | 12 | 10 |

Each table's columns serve as positive examples for their SIGDG category. The column names themselves (e.g., `drivers_license_number`, `payment_card_number`, `trade_secrets`) are the features the model learns to classify.

## Atlas Integration

Atlas provides the metadata catalog that makes Impala tables and columns visible as governed entities:

- **Entity types**: `impala_table`, `impala_column`, `impala_db` map directly to Impala's catalog objects
- **Classifications**: Applied as Atlas tags using SIGDG CURIEs (e.g., `SIGDG_0025_ContactInformation`)
- **Lineage**: Atlas tracks table-level lineage from INSERT...SELECT and CTAS operations
- **AGE graph queries**: Atlas metadata stored in PostgreSQL with AGE enables graph traversal of classification relationships, lineage paths, and impact analysis

### Atlas + Ranger Policy Flow

Once entities are tagged in Atlas:

1. Ranger policies reference SIGDG classifications (e.g., "mask all columns tagged `SIGDG:0022 PaymentInformation`")
2. Impala enforces Ranger policies at query time
3. The result: automated column masking, row filtering, and access control driven by ontology-grounded metadata tags

## Near-Term Plan

1. **Impala → Atlas hook**: Register Impala tables in Atlas when created via HMS-free DDL
2. **Tagging service prototype**: Python service that reads Atlas entities and classifies against SIGDG ontology
3. **OWL formalization**: Publish SIGDG as OWL ontology with BFO imports, verify via RASE 5-gate pipeline
4. **Ranger tag-based policies**: Column masking and access control driven by Atlas SIGDG classifications
5. **Feedback loop**: Analyst corrections to classifications improve the model over time
