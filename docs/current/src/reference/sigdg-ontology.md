# SIGDG Ontology

The Signals Data Governance ontology (prefix `SIGDG`) is grounded in BFO 2020 (Basic Formal Ontology). BFO provides the upper-level categories; SIGDG specializes them for data governance.

## BFO Grounding

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

## CURIE Prefix

```
SIGDG → https://signals360.dev/ontology/dg/
BFO   → http://purl.obolibrary.org/obo/BFO_
```

## Information Entity Hierarchy

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

## Sensitivity Levels

Sensitivity is modeled as a BFO `quality` (`BFO:0000019`) that inheres in an information entity:

| CURIE | Label | Definition |
|-------|-------|------------|
| `SIGDG:1010` | Public | Intended for unrestricted disclosure |
| `SIGDG:1020` | Internal | Not public but no harm if disclosed internally |
| `SIGDG:1030` | Confidential | Disclosure causes measurable harm to individuals or enterprise |
| `SIGDG:1040` | Restricted | Disclosure causes severe harm; regulated by law (GDPR, HIPAA, PCI) |

## Data Subject Roles

Data subjects are modeled as BFO `roles` (`BFO:0000023`), allowing the same information entity to carry different sensitivity depending on whose data it is:

| CURIE | Label | Example |
|-------|-------|---------|
| `SIGDG:2010` | CustomerRole | End-user, subscriber, app developer |
| `SIGDG:2020` | EmployeeRole | Employee, contractor, vendor |
| `SIGDG:2030` | EnterpriseRole | Corporate entity, partner organization |

A column tagged `SIGDG:0025 ContactInformation` with subject `SIGDG:2010 CustomerRole` may be `Restricted`, while the same column with subject `SIGDG:2020 EmployeeRole` may be `Confidential`.

## Data Lifecycle Processes

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
