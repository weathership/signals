# Sketch: SDG rdbms / Kudu samples for Atlas + Ranger

**Date:** 2026-08-08  
**Corpus source:** `sdg-corpora` (synth pin: `/home/rch/local/src/zndx/synth/components/sdg-corpora`)  
**Atlas types:** `rdbms_*` (already declared as `atlas_typeName` in corpus associations)

## Why this corpus

sdg-corpora ships a **reproducible relational footprint** grounded in the SDG ontology:

| Asset | Location | Signals use |
|-------|----------|-------------|
| Postgres DDL + rows | `ddl/<run>/sql/postgres/{00_schema,01_data,02_views}.sql` | Reference schema (PG load) |
| Ontology ↔ table map | `ddl/<run>/ontology_entity_associations.json` | Atlas registration + SIGDG/SKOS tags |
| SKOS vocabulary | `vocabulary/{annotations.parquet,vocabulary.ttl}` | Classification leaf codes |
| Comprehensive schema-only | `ddl-comprehensive/<run>/ddl.sql` (~5k tables) | Optional scale stress (later) |

Run of record in synth pin: **`9a0a27f5efd20aab`** — **520** base tables, associations already set  
`atlas_typeName: "rdbms_table"` and `atlas_qualifiedName` patterns (`table@cluster`).

## Product stack mapping

```
sdg-corpora DDL  ──polyglot lower──►  Impala CREATE TABLE … STORED AS KUDU
                                         │
                                         ├─► physical Kudu tablets (storage)
                                         │
                                         └─► Atlas bulk create (rdbms_instance/db/table/column)
                                               │
                                               └─► SIGDG / SDG-SKOS classifications
                                                     │
                                                     └─► Ranger tag-based policies
```

- **Do not** load 520 tables into PG as the governance source of truth for this stack.  
  PG remains **frontend** (FDW, RLS). Sample data lives in **Kudu**, governed as **`rdbms_*`**.
- Corpus `atlas_qualifiedName` uses `@aegir` in the released pin — remap to `@signals` (or `$CLUSTER_NAME`).

## Phased sample plan

### Phase S0 — Micro lab set (this week)

Hand-pick **~8–12 tables** that exercise identity + PII-ish columns for Ranger demos:

| Table (corpus) | Class (realized_from) | Why |
|----------------|----------------------|-----|
| `health_record` | (health) | client_id + record_title |
| `care_programs` | CancerSupportProgram | patient_id |
| `patient_feedback` | — | free-text quality_notes |
| `debt_case` | DebtCaseworkProcess | client_id |
| `donor_registry` | DonorProfile | display_name, contact_ref |
| `advice_sessions` | FinancialProductAdviceService | client_id, product_id |
| `discipline_cases` | — | person_id |
| `marital_cert` | — | status / consent codes |
| `t_patient` / `t_client` | spine entities | thin entity tables for join demos |

**Deliverables:**

1. `config/sdg/samples/manifest.json` — table list + cluster QN template  
2. `scripts/sdg_kudu_load.py` (or just recipe) — translate PG DDL → Impala/Kudu types  
3. Bridge register each as `rdbms_*` with QN `{db}.{table}@signals`  
4. Seed SIGDG classifications on 2–3 columns (email/name/id) for Ranger tag policy smoke  

**Kudu type mapping (v1):** all VARCHAR → STRING; PK `id` HASH-partitioned 2 tablets; no secondary indexes.

### Phase S1 — Domain slice (Atlas projections + FDW)

Load one **domain neighborhood** (~30–50 tables) with FKs, e.g. clinical/care:

- Tables from associations where `realized_from_class` ∈ {patient, care, health, clinical, donor, …}  
- Materialize Kudu tables under database `sdg_lab`  
- Register `rdbms_instance` once (`rdbms_type=Kudu`, `qualifiedName=instance@signals`)  
- Optional: upsert subset into Atlas Kudu projections (`entity_flat` / `edge_out`) for `kudu_scan` gov hops  

### Phase S2 — Full spine (520)

- Batch Impala DDL from `00_schema.sql` polyglot  
- Parallel bulk Atlas registration driven by `ontology_entity_associations.json`  
- Column roles (`sdg:SurrogateIdentifierColumn`, `sdg:ForeignKeyColumn`, `sdg:AttributeColumn`) →  
  optional custom attrs or glossary meanings (Aegir-style)  
- Ranger policies on SKOS/SIGDG tags at table scale  

### Phase S3 — Comprehensive (optional)

`ddl-comprehensive` schema-only for catalog stress; no row data; not needed for Ranger demos.

## Impala / Kudu DDL sketch (example)

```sql
CREATE DATABASE IF NOT EXISTS sdg_lab;
CREATE TABLE sdg_lab.health_record (
  id STRING,
  record_id STRING,
  condition_id STRING,
  client_id STRING,
  encoding_type STRING,
  record_title STRING,
  PRIMARY KEY (id)
) PARTITION BY HASH (id) PARTITIONS 2 STORED AS KUDU;

-- load 3–5 sample rows from 01_data.sql INSERTs (hand-picked)
```

## Atlas bulk sketch

Reuse `register_impala_table_in_atlas` / `AtlasClient.register_table`:

- instance: `instance@signals`, `rdbms_type=Kudu`  
- db: `sdg_lab@signals`  
- table/column: DESCRIBE-driven `data_type`  
- Enrichment pass: apply glossary term or classification from  
  `realized_from_class` / column `role` in associations JSON  

## Ranger sketch

1. Classification types already SIGDG on signals path  
2. Tag tables/columns after S0 register  
3. Policies: deny/mask on `SIGDG:*` Contact/Identity for non-admin Impala users  
4. Verify via Impala SQL + PG FDW `kudu_scan` as session principal (post-K5)

## Submodule recommendation

Add `components/sdg-corpora` (or `external/sdg-corpora`) as a **pinned submodule** of signals, same as synth/aegir — do not copy 520 DDL into the monorepo. Pin commit of the green HermiT-certified release.

## Immediate next engineering steps

1. ✅ Product bridge on `rdbms_*` (done)  
2. 🔲 Live tier-1 BDD green with Atlas ACTIVE on `:21010`  
3. 🔲 Submodule pin + S0 manifest + Kudu load script  
4. 🔲 Ranger tag policy smoke on S0  
5. 🔲 Optional: re-seed `atlas.entity_flat` type_name from `hive_table` → `rdbms_table` for FDW smokes  

## Notes

- Aegir Atlas `:21000` remains a **reference** for rdbms entity shape; signals advances independently.  
- Corpus still says `@aegir` in QNs — rewrite cluster suffix at load time.  
- Full 520-table Kudu load is fine for lab hardware if tablet counts stay modest (2 partitions/table).  
