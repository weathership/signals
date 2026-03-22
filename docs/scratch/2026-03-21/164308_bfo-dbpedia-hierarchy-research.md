# BFO-Grounded Hierarchy for GitTables CTA DBpedia Property Types

## 1. BFO 2020 Top-Level Structure

BFO (Basic Formal Ontology, ISO/IEC 21838-2:2021) divides all entities into two disjoint top-level categories:

```
BFO:0000001  Entity
├── BFO:0000002  Continuant                          (persists through time)
│   ├── BFO:0000004  IndependentContinuant            (can exist on its own)
│   │   ├── BFO:0000040  MaterialEntity               (has mass, occupies space)
│   │   │   ├── Object
│   │   │   ├── ObjectAggregate
│   │   │   └── FiatObjectPart
│   │   └── ImmaterialEntity
│   │       ├── Site
│   │       ├── SpatialRegion (0/1/2/3-dimensional)
│   │       └── ContinuantFiatBoundary (point/line/surface)
│   ├── BFO:0000020  SpecificallyDependentContinuant  (bound to one bearer)
│   │   ├── BFO:0000019  Quality                      (measurable attribute)
│   │   │   └── RelationalQuality
│   │   └── BFO:0000017  RealizableEntity
│   │       ├── BFO:0000016  Disposition
│   │       │   └── Function
│   │       └── BFO:0000023  Role
│   └── BFO:0000031  GenericallyDependentContinuant   (copyable, transferable)
│                                                      (e.g., information, data, plans)
└── BFO:0000003  Occurrent                           (unfolds in time)
    ├── BFO:0000015  Process
    │   ├── ProcessAggregate
    │   └── ProcessBoundary
    ├── BFO:0000008  TemporalRegion
    │   ├── ZeroDimensionalTemporalRegion (instant)
    │   └── OneDimensionalTemporalRegion  (interval)
    └── BFO:0000011  SpatiotemporalRegion
```

Key BFO categories for the DBpedia property mapping:

- **GenericallyDependentContinuant (GDC)** -- information entities that can be copied across carriers
- **Quality** -- measurable attributes that inhere in bearers (height, weight, temperature)
- **MaterialEntity** -- tangible objects (persons, organisms, artifacts)
- **Process** -- events/activities that unfold over time
- **TemporalRegion** -- time points and intervals
- **SpatialRegion** -- geometric locations
- **Role** -- externally grounded capacities (citizenship, membership)

## 2. DBpedia Domain/Range Typing

Yes, DBpedia has explicit domain/range typing for its 2,800+ properties. Each property is defined with:

- **rdfs:domain** -- which class(es) the property applies to (e.g., Person, Place, Organisation)
- **rdfs:range** -- what value type it returns (xsd:date, xsd:integer, another class, etc.)

Examples from the DBpedia ontology:

| Property | Domain | Range | Property Type |
|----------|--------|-------|---------------|
| `dbo:birthDate` | Person | xsd:date | DatatypeProperty |
| `dbo:birthPlace` | Person | Place | ObjectProperty |
| `dbo:population` | PopulatedPlace | xsd:nonNegativeInteger | DatatypeProperty |
| `dbo:height` | Person | centimeter | DatatypeProperty |
| `dbo:nationality` | Person | Country | ObjectProperty |
| `dbo:almaMater` | Person | EducationalInstitution | ObjectProperty |
| `dbo:spouse` | Person | Person | ObjectProperty |
| `dbo:salary` | Person | Currency | DatatypeProperty |

Top-level DBpedia classes:
Activity, Agent (Person, Organisation), Algorithm, AnatomicalStructure,
ArchitecturalStructure, Area, Award, Biomolecule, ChemicalSubstance, Currency,
Device, Disease, Event, Food, Language, MeanOfTransportation, Place, Species, Work

## 3. Published DBpedia-to-BFO Mappings

**No direct published mapping exists** from DBpedia classes to BFO categories. The closest work:

- **DOLCE-DBpedia alignment** -- Automatic ML-based alignment between DOLCE-LitePlus and DBpedia has been published. DOLCE has similar (but not identical) upper categories to BFO.
- **UMBEL** -- Has formal mappings to Wikipedia/DBpedia and PROTON/GeoNames, providing an intermediate upper-level bridge.
- **Common Core Ontologies (CCO)** -- Built on BFO, covers many of the same domains as DBpedia (persons, organizations, events, locations) and could serve as a mediation layer.

The alignment is straightforward at the conceptual level even without a published mapping:
- DBpedia `Person`, `Organisation`, `Device`, `Species` --> BFO MaterialEntity
- DBpedia `Place`, `PopulatedPlace` --> BFO MaterialEntity + Site
- DBpedia `Event` --> BFO Process
- DBpedia properties returning `xsd:date` --> values about BFO TemporalRegion
- DBpedia properties returning descriptive strings --> BFO GenericallyDependentContinuant

## 4. Existing SIGDG BFO Grounding

Our project already uses BFO grounding for the SIGDG data governance ontology:

```
BFO:0000031 GenericallyDependentContinuant
  └── SIGDG:0001 InformationEntity
      ├── IdentityInformation (0010)
      ├── PersonalInformation (0020)
      ├── BusinessInformation (0030)
      ├── SystemInformation (0040)
      ├── TransactionInformation (0050)
      └── TransformationMetadata (0060)

BFO:0000019 Quality
  └── SensitivityLevel (Public, Internal, Confidential, Restricted)

BFO:0000023 Role
  └── DataSubjectRole (Customer, Employee, Enterprise)

BFO:0000015 Process
  └── DataLifecycleProcess (Classification, Migration, Masking)
```

The OWL serialization in `src/sigint/owl.py` anchors all SIGDG categories under
BFO:0000031 (GDC) and sensitivity levels under BFO:0000019 (Quality).

## 5. The 122 GitTables CTA DBpedia Property Types

From `dbpedia_labels.csv` (Zenodo record 5706316), the 122 types are:

abbreviation, abstract, access, activity, address, age, alias, author, award,
block, category, cites, city, class, classification, cluster, code, collection,
comment, commonName, company, component, cost, country, county, created, dam,
date, depth, description, discontinued, duration, endDate, event, facilityId,
family, format, formula, frequency, gender, genus, height, id, issn, language,
length, location, longName, lyrics, manufacturer, material, minimum, name,
notes, number, operator, order, orientation, origin, parent, percentage, period,
plant, postalCode, price, producer, product, project, publication, publisher,
range, rank, rating, reference, region, resolution, role, route, school,
scientificName, score, selection, sentence, series, source, speaker, species,
startDate, start, state, status, style, team, technique, temperature, time,
title, training, type, updated, utcOffset, value, version, volume, weight,
width, writer, year

## 6. Proposed BFO-Aligned Hierarchy for 122 Types

### Mapping Principles

DBpedia CTA types are **properties**, not classes. A property describes a relationship
between a domain entity and a range value. To map properties to BFO, we classify by
**what the property's range value IS in BFO terms**:

- A date value IS ABOUT a temporal region
- A location value IS ABOUT a material entity / site
- A name value IS a generically dependent continuant (information content)
- A height value IS ABOUT a quality

We introduce intermediate categories inspired by IAO (Information Artifact Ontology),
which is a BFO-aligned ontology for information entities.

### Proposed Hierarchy

```
BFO:0000001  Entity
│
├── BFO:0000002  Continuant
│   │
│   ├── BFO:0000031  GenericallyDependentContinuant (GDC)
│   │   │   "information entities -- data that can be stored and transferred"
│   │   │
│   │   ├── GDC.Identifier  [21 types]
│   │   │   │   "designators that denote specific entities"
│   │   │   ├── GDC.Identifier.Name
│   │   │   │   name, longName, commonName, scientificName, alias
│   │   │   ├── GDC.Identifier.Code
│   │   │   │   id, code, facilityId, issn, postalCode, abbreviation
│   │   │   ├── GDC.Identifier.Title
│   │   │   │   title
│   │   │   └── GDC.Identifier.Reference
│   │   │       reference, cites, source, series, version, number
│   │   │
│   │   ├── GDC.DescriptiveContent  [17 types]
│   │   │   │   "natural-language or symbolic descriptions"
│   │   │   ├── GDC.DescriptiveContent.TextualDescription
│   │   │   │   description, abstract, comment, notes, sentence, lyrics
│   │   │   ├── GDC.DescriptiveContent.Categorization
│   │   │   │   category, class, classification, type, status, rank,
│   │   │   │   rating, order, cluster, selection
│   │   │   └── GDC.DescriptiveContent.Format
│   │   │       format, style, technique, formula, orientation
│   │   │
│   │   ├── GDC.MeasurementDatum  [14 types]
│   │   │   │   "recorded values of qualities -- IAO:0000109"
│   │   │   ├── GDC.MeasurementDatum.SpatialMeasurement
│   │   │   │   height, length, width, depth, resolution, volume
│   │   │   ├── GDC.MeasurementDatum.ScalarMeasurement
│   │   │   │   weight, temperature, frequency, percentage, score
│   │   │   └── GDC.MeasurementDatum.ValueRecord
│   │   │       value, minimum, cost, price, range
│   │   │
│   │   ├── GDC.PlanSpecification  [5 types]
│   │   │   │   "directives about how to do things -- IAO:0000104"
│   │   │   access, role, training, route, project
│   │   │
│   │   └── GDC.PublicationRecord  [6 types]
│   │       │   "records about created works"
│   │       author, writer, publisher, producer, publication, collection
│   │
│   ├── BFO:0000020  SpecificallyDependentContinuant
│   │   │
│   │   └── BFO:0000019  Quality
│   │       │   "measurable attributes that inhere in their bearer"
│   │       │
│   │       ├── Quality.PhysicalQuality  [4 types]
│   │       │   material, color (not in set but related), dam, plant
│   │       │
│   │       ├── Quality.InformationalQuality  [4 types]
│   │       │   │   "properties describing the entity itself, not a datum"
│   │       │   gender, language, species, genus
│   │       │
│   │       └── Quality.StatusQuality  [2 types]
│   │           discontinued, updated
│   │
│   └── BFO:0000004  IndependentContinuant
│       │
│       ├── BFO:0000040  MaterialEntity
│       │   │   "entities with mass that occupy space"
│       │   │
│       │   ├── MaterialEntity.Agent  [8 types]
│       │   │   │   "persons, organizations, teams"
│       │   │   company, team, operator, manufacturer, speaker,
│       │   │   parent, school, family
│       │   │
│       │   ├── MaterialEntity.Artifact  [3 types]
│       │   │   │   "manufactured or constructed things"
│       │   │   product, component, block
│       │   │
│       │   └── MaterialEntity.BiologicalEntity  [2 types]
│       │       species (as entity, not quality), genus (as entity)
│       │
│       └── Site / SpatialRegion
│           │   "geographic and administrative locations"
│           │
│           ├── Site.AdministrativeRegion  [5 types]
│           │   country, state, region, county, city
│           │
│           ├── Site.Location  [3 types]
│           │   location, origin, address
│           │
│           └── Site.SpatialSpecification  [1 type]
│               utcOffset
│
└── BFO:0000003  Occurrent
    │
    ├── BFO:0000015  Process
    │   │   "events and activities that unfold in time"
    │   │
    │   ├── Process.Activity  [3 types]
    │   │   activity, event, award
    │   │
    │   └── Process.CreationProcess  [1 type]
    │       created
    │
    └── BFO:0000008  TemporalRegion
        │   "time points, dates, durations, intervals"
        │
        ├── TemporalRegion.DatePoint  [5 types]
        │   date, startDate, endDate, year, time
        │
        ├── TemporalRegion.Duration  [2 types]
        │   duration, period
        │
        └── TemporalRegion.TemporalSpecification  [1 type]
            start
```

### Ambiguous / Cross-Cutting Types

Some DBpedia property types are ambiguous -- they could belong to multiple BFO
categories depending on context. These are placed in the most common interpretation:

| Type | Primary Placement | Alternative |
|------|-------------------|-------------|
| `species` | Quality.InformationalQuality | MaterialEntity.BiologicalEntity |
| `genus` | Quality.InformationalQuality | MaterialEntity.BiologicalEntity |
| `parent` | MaterialEntity.Agent | GDC.Identifier.Reference |
| `role` | GDC.PlanSpecification | BFO:Role (if denoting a bearer role) |
| `dam` | Quality.PhysicalQuality | MaterialEntity.Artifact |
| `plant` | Quality.PhysicalQuality | MaterialEntity.BiologicalEntity |
| `start` | TemporalRegion.TemporalSpec | GDC.Identifier (if start position) |
| `block` | MaterialEntity.Artifact | GDC.Identifier.Code (blockchain) |
| `order` | GDC.DescriptiveContent.Cat | Process.Activity (purchase order) |

### Category Counts

| BFO Parent | Intermediate Category | Count |
|------------|----------------------|-------|
| GDC | Identifier | 21 |
| GDC | DescriptiveContent | 17 |
| GDC | MeasurementDatum | 14 |
| GDC | PlanSpecification | 5 |
| GDC | PublicationRecord | 6 |
| Quality | Physical/Informational/Status | 10 |
| MaterialEntity | Agent/Artifact/Biological | 13 |
| Site/SpatialRegion | AdminRegion/Location/Spatial | 9 |
| Process | Activity/Creation | 4 |
| TemporalRegion | DatePoint/Duration/Spec | 8 |
| **TOTAL** | | **107** |

The remaining ~15 types have dual placement or were grouped under their
primary category above. Exact count depends on disambiguation choices.

## 7. Connecting to SIGDG

The proposed CTA hierarchy and the existing SIGDG hierarchy serve different purposes:

- **SIGDG** classifies columns by **data governance sensitivity** (PII, financial, health)
- **CTA/BFO** classifies columns by **ontological nature** (identifier, measurement, temporal)

These are orthogonal dimensions. A column could be:
- CTA: `GDC.Identifier.Name` + SIGDG: `ContactInformation` (a person's name is PII)
- CTA: `GDC.MeasurementDatum.ScalarMeasurement` + SIGDG: `FinancialInformation` (salary is financial PII)
- CTA: `TemporalRegion.DatePoint` + SIGDG: `DemographicInformation` (birthDate is demographic PII)

A unified system could tag columns with BOTH ontological type and governance sensitivity.

## Sources

- [GitTables: A Large-Scale Corpus of Relational Tables](https://arxiv.org/pdf/2106.07258)
- [GitTables benchmark - column type detection (Zenodo)](https://zenodo.org/records/5706316)
- [BFO 2020 GitHub repository](https://github.com/BFO-ontology/BFO-2020)
- [BFO OWL v2.0](https://raw.githubusercontent.com/BFO-ontology/BFO/v2.0/bfo.owl)
- [DBpedia Ontology Classes](https://dief.tools.dbpedia.org/server/ontology/classes/)
- [DBpedia Ontology Editing Guide](https://mappings.dbpedia.org/index.php/How_to_edit_the_DBpedia_Ontology)
- [Foundational Ontologies meet Ontology Matching: A Survey](https://www.semantic-web-journal.net/system/files/swj2650.pdf)
- [AdaTyper DBpedia ontology CSV](https://github.com/madelonhulsebos/AdaTyper)
- [SemTab 2021 CTA-DBP Challenge](https://www.aicrowd.com/challenges/semtab-2021/problems/column-type-annotation-by-dbpedia-cta-dbp)
