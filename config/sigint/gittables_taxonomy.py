"""BFO-grounded hierarchy over 122 GitTables CTA DBpedia property types.

Maps all 122 DBpedia property types from Zenodo 5706316 to BFO categories
based on what the column value IS in BFO terms (e.g. a date value is about a
TemporalRegion, a name value is a GenericallyDependentContinuant).

The hierarchy gives DST internal focal elements for cautious classification:
when the classifier can't distinguish "start date" from "end date", mass goes
to the TemporalRegion parent node instead of being split between singletons.

Leaf codes use the exact annotation_label strings from dbpedia_labels.csv
(e.g. "start date" not "startDate") to match ground truth at evaluation time.

Reference: Zenodo 5706316 (GitTables CTA benchmark)
BFO: ISO/IEC 21838-2:2021 (Basic Formal Ontology)
"""

from __future__ import annotations

from sigint.category_set import HierarchicalCategorySet, ReferenceCategory

# ── Internal (parent) nodes ─────────────────────────────────────────
#
# Dotted codes encode the BFO tree path.

_INTERNAL_NODES: list[dict] = [
    # Root
    {"code": "entity", "label": "Entity", "parent": None,
     "text": "entity | any kind of column value"},
    # L1
    {"code": "continuant", "label": "Continuant", "parent": "entity",
     "text": "continuant | persistent entity | thing that endures through time"},
    {"code": "occurrent", "label": "Occurrent", "parent": "entity",
     "text": "occurrent | event or process | thing that unfolds in time"},
    # L2 under Continuant
    {"code": "continuant.gdc", "label": "GenericallyDependentContinuant", "parent": "continuant",
     "text": "information entity | data that can be stored, copied, and transferred"},
    {"code": "continuant.quality", "label": "Quality", "parent": "continuant",
     "text": "quality | measurable attribute that inheres in a bearer"},
    {"code": "continuant.ic", "label": "IndependentContinuant", "parent": "continuant",
     "text": "independent continuant | entity that can exist on its own"},
    # L3 under GDC
    {"code": "continuant.gdc.identifier", "label": "Identifier", "parent": "continuant.gdc",
     "text": "identifier | designator that denotes a specific entity | name, code, ID"},
    {"code": "continuant.gdc.descriptive", "label": "DescriptiveContent", "parent": "continuant.gdc",
     "text": "descriptive content | natural-language or symbolic description"},
    {"code": "continuant.gdc.measurement", "label": "MeasurementDatum", "parent": "continuant.gdc",
     "text": "measurement datum | recorded value of a quality | numeric measurement"},
    {"code": "continuant.gdc.plan", "label": "PlanSpecification", "parent": "continuant.gdc",
     "text": "plan specification | directive about how to do things"},
    {"code": "continuant.gdc.publication", "label": "PublicationRecord", "parent": "continuant.gdc",
     "text": "publication record | record about a created work or its creator"},
    # L4 under Identifier
    {"code": "continuant.gdc.identifier.name", "label": "NameIdentifier", "parent": "continuant.gdc.identifier",
     "text": "name identifier | proper name or label for an entity"},
    {"code": "continuant.gdc.identifier.code", "label": "CodeIdentifier", "parent": "continuant.gdc.identifier",
     "text": "code identifier | numeric or alphanumeric code, ID, serial number"},
    {"code": "continuant.gdc.identifier.title", "label": "TitleIdentifier", "parent": "continuant.gdc.identifier",
     "text": "title | formal title of a work, position, or entity"},
    {"code": "continuant.gdc.identifier.reference", "label": "ReferenceIdentifier", "parent": "continuant.gdc.identifier",
     "text": "reference | citation, source link, series, version number"},
    # L4 under DescriptiveContent
    {"code": "continuant.gdc.descriptive.text", "label": "TextualDescription", "parent": "continuant.gdc.descriptive",
     "text": "textual description | free text description, abstract, comment, notes"},
    {"code": "continuant.gdc.descriptive.categorization", "label": "Categorization", "parent": "continuant.gdc.descriptive",
     "text": "categorization | category, class, type, status, rank, rating"},
    {"code": "continuant.gdc.descriptive.format", "label": "FormatSpecification", "parent": "continuant.gdc.descriptive",
     "text": "format specification | format, style, technique, formula"},
    # L4 under MeasurementDatum
    {"code": "continuant.gdc.measurement.spatial", "label": "SpatialMeasurement", "parent": "continuant.gdc.measurement",
     "text": "spatial measurement | height, length, width, depth, area, volume"},
    {"code": "continuant.gdc.measurement.scalar", "label": "ScalarMeasurement", "parent": "continuant.gdc.measurement",
     "text": "scalar measurement | weight, temperature, frequency, score, percentage"},
    {"code": "continuant.gdc.measurement.value", "label": "ValueRecord", "parent": "continuant.gdc.measurement",
     "text": "value record | monetary value, cost, price, range, minimum"},
    # L3 under Quality
    {"code": "continuant.quality.physical", "label": "PhysicalQuality", "parent": "continuant.quality",
     "text": "physical quality | material, physical structure"},
    {"code": "continuant.quality.informational", "label": "InformationalQuality", "parent": "continuant.quality",
     "text": "informational quality | gender, language, species, genus"},
    {"code": "continuant.quality.status", "label": "StatusQuality", "parent": "continuant.quality",
     "text": "status quality | lifecycle status, active/discontinued"},
    # L3 under IndependentContinuant
    {"code": "continuant.ic.agent", "label": "Agent", "parent": "continuant.ic",
     "text": "agent | person, organization, team, operator"},
    {"code": "continuant.ic.artifact", "label": "Artifact", "parent": "continuant.ic",
     "text": "artifact | manufactured or constructed thing, product, component"},
    {"code": "continuant.ic.site", "label": "Site", "parent": "continuant.ic",
     "text": "site | geographic or administrative location"},
    # L4 under Site
    {"code": "continuant.ic.site.admin", "label": "AdministrativeRegion", "parent": "continuant.ic.site",
     "text": "administrative region | country, state, county, city"},
    {"code": "continuant.ic.site.location", "label": "Location", "parent": "continuant.ic.site",
     "text": "location | geographic location, address, origin"},
    {"code": "continuant.ic.site.spatial", "label": "SpatialSpecification", "parent": "continuant.ic.site",
     "text": "spatial specification | UTC offset, coordinates, spatial reference"},
    # L2 under Occurrent
    {"code": "occurrent.process", "label": "Process", "parent": "occurrent",
     "text": "process | event or activity that unfolds in time"},
    {"code": "occurrent.temporal", "label": "TemporalRegion", "parent": "occurrent",
     "text": "temporal region | time point, date, duration, interval"},
    # L3 under Process
    {"code": "occurrent.process.activity", "label": "Activity", "parent": "occurrent.process",
     "text": "activity | event, award, organized activity"},
    {"code": "occurrent.process.creation", "label": "CreationProcess", "parent": "occurrent.process",
     "text": "creation process | the act of creating something"},
    # L3 under TemporalRegion
    {"code": "occurrent.temporal.datepoint", "label": "DatePoint", "parent": "occurrent.temporal",
     "text": "date point | specific date, start date, end date, year"},
    {"code": "occurrent.temporal.duration", "label": "Duration", "parent": "occurrent.temporal",
     "text": "duration | time period, duration, interval length"},
    {"code": "occurrent.temporal.spec", "label": "TemporalSpecification", "parent": "occurrent.temporal",
     "text": "temporal specification | start position or time marker"},
]

# ── Leaf nodes (122 DBpedia property types) ─────────────────────────
#
# Each entry: (annotation_label, parent_code, embedding_text)
# annotation_label matches dbpedia_labels.csv exactly (space-separated).

_LEAF_TYPES: list[tuple[str, str, str]] = [
    # === GDC.Identifier.Name (6) ===
    ("name", "continuant.gdc.identifier.name",
     "name | proper name or label | values are capitalized person, place, or entity names like Alice, New York, Toyota | high cardinality, mostly unique"),
    ("long name", "continuant.gdc.identifier.name",
     "long name | full or extended name | values are multi-word proper names or titles, longer than typical name fields"),
    ("common name", "continuant.gdc.identifier.name",
     "common name | vernacular or widely-used name | values are informal everyday names like cat, oak, flu"),
    ("scientific name", "continuant.gdc.identifier.name",
     "scientific name | formal taxonomic designation | values are Latin binomial names like Homo sapiens, Quercus robur"),
    ("alias", "continuant.gdc.identifier.name",
     "alias | alternative name, pseudonym, nickname | values are alternate labels or known-as names for the same entity"),
    ("prefix", "continuant.gdc.identifier.name",
     "prefix | name prefix or honorific | values are short titles like Mr, Mrs, Dr, Prof, Sr"),

    # === GDC.Identifier.Code (8) ===
    ("id", "continuant.gdc.identifier.code",
     "id | unique identifier, primary key | values are sequential integers like 1 2 3 or alphanumeric codes, high cardinality, each value unique"),
    ("code", "continuant.gdc.identifier.code",
     "code | classification code, symbolic identifier | values are short alphanumeric codes like US, EUR, A1, ISO codes"),
    ("facility id", "continuant.gdc.identifier.code",
     "facility id | identifier for a facility or site | values are alphanumeric facility codes or building numbers"),
    ("issn", "continuant.gdc.identifier.code",
     "issn | International Standard Serial Number | values are 8-digit serial numbers in NNNN-NNNN format"),
    ("postal code", "continuant.gdc.identifier.code",
     "postal code | ZIP code, postcode | values are short alphanumeric postal codes like 90210, SW1A 1AA, 75001"),
    ("zip code", "continuant.gdc.identifier.code",
     "zip code | postal ZIP code | values are 5 or 9-digit US ZIP codes like 90210, 10001-1234"),
    ("abbreviation", "continuant.gdc.identifier.code",
     "abbreviation | shortened form of a name | values are short uppercase letter sequences like USA, NYC, DNA, HTML"),
    ("fc", "continuant.gdc.identifier.code",
     "fc | football club identifier or function code | values are club abbreviations or short alphanumeric function codes"),

    # === GDC.Identifier.Title (1) ===
    ("title", "continuant.gdc.identifier.title",
     "title | formal title of a work or position | values are book titles, movie names, job titles, or article headlines, medium-length text"),

    # === GDC.Identifier.Reference (6) ===
    ("reference", "continuant.gdc.identifier.reference",
     "reference | citation or link to a resource | values are URLs, DOIs, bibliographic references, or document identifiers"),
    ("cites", "continuant.gdc.identifier.reference",
     "cites | bibliographic citation | values are formatted citations or reference strings to other works"),
    ("source", "continuant.gdc.identifier.reference",
     "source | origin or provenance of data | values are dataset names, organization names, or URLs indicating where data came from"),
    ("series", "continuant.gdc.identifier.reference",
     "series | named series or collection | values are series names like Season 1, Vol. 3, Series A"),
    ("version", "continuant.gdc.identifier.reference",
     "version | version number or edition | values are version strings like 1.0, v2.3.1, 2nd Edition"),
    ("number", "continuant.gdc.identifier.reference",
     "number | generic numeric identifier, issue number | values are integers used as issue numbers, sequence numbers, or episode numbers"),

    # === GDC.DescriptiveContent.Text (8) ===
    ("description", "continuant.gdc.descriptive.text",
     "description | free text description | values are long natural language paragraphs describing an entity, high average length"),
    ("abstract", "continuant.gdc.descriptive.text",
     "abstract | summary of a document or article | values are multi-sentence summaries, typically 100-300 words of academic or technical prose"),
    ("comment", "continuant.gdc.descriptive.text",
     "comment | user comment or remark | values are user-generated text of varying length, opinions or feedback"),
    ("notes", "continuant.gdc.descriptive.text",
     "notes | additional notes or supplementary info | values are free text notes, varying length, informal annotation"),
    ("note", "continuant.gdc.descriptive.text",
     "note | single note or annotation | values are individual text annotations or remarks, shorter than notes"),
    ("sentence", "continuant.gdc.descriptive.text",
     "sentence | a sentence of natural language text | values are single complete sentences of natural language"),
    ("lyrics", "continuant.gdc.descriptive.text",
     "lyrics | song lyrics or verse text | values are lines or stanzas of song lyrics, poetic text"),
    ("definition", "continuant.gdc.descriptive.text",
     "definition | formal definition of a term | values are dictionary-style definitions explaining meaning of terms"),

    # === GDC.DescriptiveContent.Categorization (12) ===
    ("category", "continuant.gdc.descriptive.categorization",
     "category | classification category or grouping | values are short categorical labels from a finite set, low cardinality, many repeated values"),
    ("class", "continuant.gdc.descriptive.categorization",
     "class | class label, taxonomic class, or group | values are short categorical labels like Class A, mammal, positive, low cardinality"),
    ("classification", "continuant.gdc.descriptive.categorization",
     "classification | assigned classification or taxonomy label | values are classification labels from a controlled vocabulary, low cardinality"),
    ("type", "continuant.gdc.descriptive.categorization",
     "type | entity type, kind, or variety | values are short categorical type labels from a finite set, low cardinality, many repeated values"),
    ("status", "continuant.gdc.descriptive.categorization",
     "status | current status, state, or condition | values are short status labels like active, pending, closed, completed, very low cardinality"),
    ("rank", "continuant.gdc.descriptive.categorization",
     "rank | position in an ordered hierarchy | values are ordinal labels or integers indicating position like 1st, 2nd, Captain, Major"),
    ("rating", "continuant.gdc.descriptive.categorization",
     "rating | quality rating or review score | values are ratings like 4.5, PG-13, AAA, 3 stars, from a bounded scale"),
    ("order", "continuant.gdc.descriptive.categorization",
     "order | sort order or taxonomic order | values are integers or labels indicating sequence position or biological order"),
    ("cluster", "continuant.gdc.descriptive.categorization",
     "cluster | grouping or partition label | values are cluster identifiers like Cluster 0, Group A, low cardinality"),
    ("selection", "continuant.gdc.descriptive.categorization",
     "selection | selected item or choice | values are labels indicating a chosen option from a set"),
    ("field", "continuant.gdc.descriptive.categorization",
     "field | field of study or domain | values are discipline names like physics, biology, computer science, low cardinality"),
    ("focus", "continuant.gdc.descriptive.categorization",
     "focus | primary focus or subject area | values are topic labels indicating area of attention or specialization"),

    # === GDC.DescriptiveContent.Format (5) ===
    ("format", "continuant.gdc.descriptive.format",
     "format | data format or encoding | values are short technical labels like PDF, JSON, MP3, CSV, JPEG, low cardinality"),
    ("style", "continuant.gdc.descriptive.format",
     "style | artistic or design style | values are style labels like Gothic, Modern, Bold, Italic"),
    ("technique", "continuant.gdc.descriptive.format",
     "technique | method or approach used | values are technique names like watercolor, regression, PCR"),
    ("formula", "continuant.gdc.descriptive.format",
     "formula | mathematical or chemical formula | values are symbolic expressions like H2O, E=mc2, C6H12O6"),
    ("orientation", "continuant.gdc.descriptive.format",
     "orientation | spatial orientation or direction | values are direction labels like North, landscape, portrait, left-to-right"),

    # === GDC.MeasurementDatum.Spatial (7) ===
    ("height", "continuant.gdc.measurement.spatial",
     "height | vertical measurement | values are decimal numbers with physical units like 1.75, 5.9, 180, representing meters or centimeters"),
    ("length", "continuant.gdc.measurement.spatial",
     "length | linear measurement or distance | values are decimal numbers representing distance like 10.5, 3.2, in meters, km, or miles"),
    ("width", "continuant.gdc.measurement.spatial",
     "width | horizontal measurement or breadth | values are decimal numbers for width dimensions like 2.5, 15.0"),
    ("depth", "continuant.gdc.measurement.spatial",
     "depth | measurement of depth | values are decimal numbers for depth below surface like 3.5, 100.0"),
    ("resolution", "continuant.gdc.measurement.spatial",
     "resolution | spatial or display resolution | values are pixel dimensions or density numbers like 1920, 72, 300dpi"),
    ("volume", "continuant.gdc.measurement.spatial",
     "volume | three-dimensional measurement | values are decimal numbers for capacity or volume like 2.5, 500, in liters or cubic meters"),
    ("capacity", "continuant.gdc.measurement.spatial",
     "capacity | maximum volume or throughput | values are decimal numbers for maximum capacity like 1000, 50.5"),

    # === GDC.MeasurementDatum.Scalar (6) ===
    ("weight", "continuant.gdc.measurement.scalar",
     "weight | mass measurement | values are decimal numbers for mass like 75.5, 2.3, in kilograms, pounds, or grams"),
    ("temperature", "continuant.gdc.measurement.scalar",
     "temperature | thermal measurement | values are decimal numbers for temperature like 36.6, 98.6, -10.5, in degrees C or F"),
    ("frequency", "continuant.gdc.measurement.scalar",
     "frequency | rate of occurrence | values are decimal numbers for frequency like 440, 2.4, in Hz, GHz, or count per unit time"),
    ("percentage", "continuant.gdc.measurement.scalar",
     "percentage | ratio as fraction of 100 | values are decimal numbers between 0 and 100 like 45.5, 99.9, 12.3"),
    ("score", "continuant.gdc.measurement.scalar",
     "score | numeric score or evaluation result | values are decimal numbers representing points or scores like 85.5, 3.7, 100"),
    ("ons", "continuant.gdc.measurement.scalar",
     "ons | Office for National Statistics metric | values are numeric statistical measures or codes from ONS datasets"),

    # === GDC.MeasurementDatum.Value (5) ===
    ("value", "continuant.gdc.measurement.value",
     "value | generic numeric value, quantity | values are decimal or integer numbers representing measured amounts"),
    ("min", "continuant.gdc.measurement.value",
     "min | minimum value or lower bound | values are decimal numbers representing the lowest value in a range"),
    ("cost", "continuant.gdc.measurement.value",
     "cost | monetary cost or expense | values are decimal numbers for money like 19.99, 1500.00, representing currency amounts"),
    ("price", "continuant.gdc.measurement.value",
     "price | monetary price or listing price | values are decimal numbers for prices like 9.99, 249.00, representing selling price"),
    ("range", "continuant.gdc.measurement.value",
     "range | value range or span between bounds | values are numeric ranges or interval descriptions like 10-20, 0.5-1.0"),

    # === GDC.PlanSpecification (7) ===
    ("access", "continuant.gdc.plan",
     "access | access level or permission | values are short labels like public, private, restricted, admin, low cardinality"),
    ("role", "continuant.gdc.plan",
     "role | assigned role or responsibility | values are role labels like admin, editor, viewer, manager, low cardinality"),
    ("training", "continuant.gdc.plan",
     "training | training program or educational track | values are training names or course titles like Safety Training, Onboarding"),
    ("route", "continuant.gdc.plan",
     "route | path, route, or itinerary | values are route names, road numbers, or path descriptions like Route 66, I-95"),
    ("project", "continuant.gdc.plan",
     "project | project name or initiative | values are project names like Apollo, Manhattan Project, or alphanumeric project codes"),
    ("portfolio", "continuant.gdc.plan",
     "portfolio | collection of projects or investments | values are portfolio names or grouping labels for investment or project sets"),
    ("subsystem", "continuant.gdc.plan",
     "subsystem | component subsystem or module | values are subsystem names or module identifiers within a larger system"),

    # === GDC.PublicationRecord (6) ===
    ("author", "continuant.gdc.publication",
     "author | author name | values are person names like John Smith, J.K. Rowling, format is First Last or Last, First"),
    ("writer", "continuant.gdc.publication",
     "writer | writer name or screenwriter | values are person names of content creators, screenwriters, or journalists"),
    ("publisher", "continuant.gdc.publication",
     "publisher | publishing company or press | values are organization names like Penguin, Oxford University Press, Springer"),
    ("producer", "continuant.gdc.publication",
     "producer | producer name or manufacturer | values are person or company names who produce media content or goods"),
    ("publication", "continuant.gdc.publication",
     "publication | publication name or journal title | values are journal, newspaper, or magazine names like Nature, The Times"),
    ("collection", "continuant.gdc.publication",
     "collection | collection name or anthology | values are names of curated sets, anthologies, or museum collections"),

    # === Quality.Physical (4) ===
    ("material", "continuant.quality.physical",
     "material | physical material or substance | values are material names like steel, wood, plastic, cotton, low cardinality"),
    ("age", "continuant.quality.physical",
     "age | age in years or time units | values are integers or decimals representing age like 25, 3.5, 100"),
    ("dam", "continuant.quality.physical",
     "dam | dam structure or water barrier | values are dam names or identifiers like Hoover Dam, Three Gorges"),
    ("plant", "continuant.quality.physical",
     "plant | plant species or facility | values are plant names like Oak, Rose, or factory names like Plant A"),

    # === Quality.Informational (4) ===
    ("gender", "continuant.quality.informational",
     "gender | gender identity | values are gender labels like Male, Female, Non-binary, M, F, very low cardinality"),
    ("language", "continuant.quality.informational",
     "language | spoken or written language | values are language names or ISO codes like English, French, en, fr, de"),
    ("species", "continuant.quality.informational",
     "species | biological species | values are species names like Canis lupus, Homo sapiens, or common species names"),
    ("genus", "continuant.quality.informational",
     "genus | biological genus | values are taxonomic genus names like Canis, Homo, Quercus, Latin single words"),

    # === Quality.Status (2) ===
    ("discontinued", "continuant.quality.status",
     "discontinued | whether item is discontinued | values are boolean-like labels: Yes, No, True, False, 0, 1, very low cardinality"),
    ("updated", "continuant.quality.status",
     "updated | last updated timestamp | values are date-time strings indicating when a record was last modified"),

    # === IndependentContinuant.Agent (9) ===
    ("company", "continuant.ic.agent",
     "company | company name, corporation | values are organization names like Google, Toyota, Microsoft, high cardinality"),
    ("team", "continuant.ic.agent",
     "team | team name, sports team, or work group | values are team names like Lakers, Red Sox, Engineering Team, medium cardinality"),
    ("operator", "continuant.ic.agent",
     "operator | operator name or service provider | values are company or person names who operate services or equipment"),
    ("manufacturer", "continuant.ic.agent",
     "manufacturer | manufacturing company or brand | values are company names like Samsung, Boeing, Ford, medium cardinality"),
    ("speaker", "continuant.ic.agent",
     "speaker | speaker name or presenter | values are person names of speakers, presenters, or narrators"),
    ("parent", "continuant.ic.agent",
     "parent | parent entity or parent organization | values are organization or entity names of the parent company or group"),
    ("school", "continuant.ic.agent",
     "school | school name, educational institution | values are school or university names like Harvard, MIT, Lincoln High"),
    ("family", "continuant.ic.agent",
     "family | family name or taxonomic family | values are family surnames or biological family names like Canidae, Rosaceae"),
    ("department", "continuant.ic.agent",
     "department | department name or organizational unit | values are department labels like Sales, Engineering, HR, low cardinality"),

    # === IndependentContinuant.Artifact (3) ===
    ("product", "continuant.ic.artifact",
     "product | product name or commercial good | values are product names like iPhone, Model 3, or product descriptions, high cardinality"),
    ("component", "continuant.ic.artifact",
     "component | component part or module | values are component names like CPU, Battery, Wheel, identifying parts of a system"),
    ("block", "continuant.ic.artifact",
     "block | block identifier or city block | values are block numbers or identifiers like Block A, 1200, grid references"),

    # === Site.AdministrativeRegion (5) ===
    ("country", "continuant.ic.site.admin",
     "country | country name, nation | values are country names like United States, Germany, Japan, low cardinality, repeated"),
    ("state", "continuant.ic.site.admin",
     "state | state, province, or administrative division | values are state or province names like California, Ontario, Bavaria"),
    ("region", "continuant.ic.site.admin",
     "region | geographic region or territory | values are region names like Northeast, Asia Pacific, Midwest, low cardinality"),
    ("county", "continuant.ic.site.admin",
     "county | county or district name | values are county names like Los Angeles County, Kent, medium cardinality"),
    ("city", "continuant.ic.site.admin",
     "city | city name, town, municipality | values are city names like New York, London, Tokyo, medium-high cardinality"),

    # === Site.Location (4) ===
    ("location", "continuant.ic.site.location",
     "location | geographic location or place | values are place names, addresses, or location descriptions, varied format"),
    ("origin", "continuant.ic.site.location",
     "origin | place of origin or birthplace | values are location names indicating where something or someone came from"),
    ("address", "continuant.ic.site.location",
     "address | street address or mailing address | values are multi-part addresses like 123 Main St, Apt 4, with street and number"),
    ("space", "continuant.ic.site.location",
     "space | physical space or venue | values are space or venue names like Room 101, Hall B, Conference Center"),

    # === Site.SpatialSpecification (1) ===
    ("utc offset", "continuant.ic.site.spatial",
     "utc offset | UTC time zone offset | values are timezone offsets like +05:00, -08:00, UTC+1, low cardinality"),

    # === Process.Activity (3) ===
    ("activity", "occurrent.process.activity",
     "activity | activity type or organized action | values are activity names like Swimming, Meeting, Conference, low-medium cardinality"),
    ("event", "occurrent.process.activity",
     "event | event name or occurrence | values are event names like World Cup, Election, Conference 2024, high cardinality"),
    ("award", "occurrent.process.activity",
     "award | award name or recognition | values are award names like Nobel Prize, Grammy, Oscar, medium cardinality"),

    # === Process.Creation (1) ===
    ("created", "occurrent.process.creation",
     "created | creation date | values are date-time strings in YYYY-MM-DD or ISO format indicating when entity was first created"),

    # === TemporalRegion.DatePoint (6) ===
    ("date", "occurrent.temporal.datepoint",
     "date | calendar date | values are date strings in YYYY-MM-DD or similar format, temporal sequence of specific days"),
    ("start date", "occurrent.temporal.datepoint",
     "start date | beginning date of an event or period | values are date strings in YYYY-MM-DD format marking the start of something"),
    ("end date", "occurrent.temporal.datepoint",
     "end date | ending date of an event or period | values are date strings in YYYY-MM-DD format marking the end of something"),
    ("year", "occurrent.temporal.datepoint",
     "year | calendar year | values are four-digit year numbers like 2020, 1999, 1776, integer format"),
    ("time", "occurrent.temporal.datepoint",
     "time | time of day or timestamp | values are time strings like 14:30:00, 8:00 AM, or full timestamps with date and time"),
    ("second", "occurrent.temporal.datepoint",
     "second | second of time | values are numeric seconds like 30, 59.5, or sub-minute time measurements"),

    # === TemporalRegion.Duration (2) ===
    ("duration", "occurrent.temporal.duration",
     "duration | length of time or interval | values are duration expressions like 2 hours, 30 min, 1.5, or numeric time spans"),
    ("period", "occurrent.temporal.duration",
     "period | time period or era | values are period labels like Q1 2024, Renaissance, 1990-2000, or named intervals"),

    # === TemporalRegion.TemporalSpecification (1) ===
    ("start", "occurrent.temporal.spec",
     "start | starting point or initial marker | values are numeric positions or timestamps marking the beginning of an interval"),
]

# ── Confusable pairs ────────────────────────────────────────────────
#
# Known-ambiguous pairs identified from semantic proximity analysis.
# Uses the exact annotation_label strings from dbpedia_labels.csv.

GITTABLES_CONFUSABLE_PAIRS: list[tuple[str, str]] = [
    # Name variants
    ("name", "long name"),
    ("name", "common name"),
    ("name", "scientific name"),
    ("name", "alias"),
    ("long name", "common name"),
    # Date/time variants
    ("start date", "date"),
    ("end date", "date"),
    ("start date", "end date"),
    ("date", "year"),
    ("date", "time"),
    ("duration", "period"),
    # Location variants
    ("country", "region"),
    ("city", "location"),
    ("state", "region"),
    ("location", "address"),
    ("location", "origin"),
    ("location", "space"),
    # Description variants
    ("description", "abstract"),
    ("description", "comment"),
    ("description", "notes"),
    ("description", "definition"),
    ("abstract", "comment"),
    ("notes", "note"),
    # Organization variants
    ("company", "team"),
    ("company", "manufacturer"),
    ("company", "publisher"),
    ("operator", "manufacturer"),
    ("company", "department"),
    # Categorization variants
    ("category", "type"),
    ("category", "class"),
    ("category", "classification"),
    ("type", "class"),
    ("status", "rank"),
    ("rank", "rating"),
    ("field", "focus"),
    # Measurement variants
    ("cost", "price"),
    ("value", "score"),
    ("height", "length"),
    ("width", "length"),
    ("volume", "capacity"),
    ("min", "value"),
    # Authorship variants
    ("author", "writer"),
    ("publisher", "producer"),
    # ID variants
    ("id", "code"),
    ("reference", "source"),
    ("reference", "cites"),
    ("postal code", "zip code"),
]


# ── Pattern → GitTables category map ──────────────────────────────

GITTABLES_PATTERN_MAP: dict[str, str] = {
    "date_iso_pattern": "date",
    "email_pattern": "address",
    "url_pattern": "reference",
    "uuid_pattern": "id",
    "ipv4_pattern": "address",
    "phone_pattern": "number",
    "credit_card_pattern": "id",
    "ssn_pattern": "code",
}


def _build_leaf(label: str, parent_code: str, embedding_text: str) -> ReferenceCategory:
    """Build a leaf ReferenceCategory for a DBpedia property type."""
    return ReferenceCategory(
        code=label,
        label=label,
        embedding_text=embedding_text,
        taxonomy="gittables",
        parent_code=parent_code,
    )


def _build_internal(node: dict) -> ReferenceCategory:
    """Build an internal (parent) ReferenceCategory from a node dict."""
    return ReferenceCategory(
        code=node["code"],
        label=node["label"],
        embedding_text=node["text"],
        taxonomy="gittables",
        parent_code=node["parent"],
    )


def gittables_category_set() -> HierarchicalCategorySet:
    """Build a HierarchicalCategorySet for the 122 GitTables CTA DBpedia types.

    Returns a category set with:
    - 122 leaf categories (one per DBpedia property type)
    - ~36 internal nodes (BFO-aligned hierarchy)
    - Confusable pairs registered for DST belief functions
    """
    leaves = [_build_leaf(label, parent, text) for label, parent, text in _LEAF_TYPES]
    internals = [_build_internal(node) for node in _INTERNAL_NODES]
    all_categories = leaves + internals

    return HierarchicalCategorySet(
        name="gittables",
        categories=leaves,
        all_categories=all_categories,
    )


def get_leaf_labels() -> list[str]:
    """Return the 122 DBpedia property labels (leaf codes)."""
    return [label for label, _, _ in _LEAF_TYPES]
