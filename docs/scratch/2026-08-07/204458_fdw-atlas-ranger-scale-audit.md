# FDW audit for Atlas/Ranger scale on PG+AGE → Kudu

**Objective (product):** scale and accelerate **Atlas** and **Ranger** operations that today sit on the “pglite” governance plane (Postgres 16 + AGE as Atlas graph backend, Ranger admin/tag store on PG), using **Kudu via impala_fdw** as the high-throughput data path—without turning the FDW into a second Atlas/Ranger engine.

**Aegir:** can generate representative Atlas graph load (sample entities/classifications). **Ranger:** greenfield for TagSync + tag-based Impala policy in this stack.

---

## 1. Architecture split (recommended)

Do **not** try to host AGE Cypher topology on Kudu. AGE needs local relation storage for openCypher (`atlas_graph.vertex`, edges, functional indexes). Kudu + FDW is the wrong substrate for that.

| Plane | Stays on Postgres (+ AGE) | Move / mirror to Kudu (FDW-facing) |
|-------|---------------------------|-------------------------------------|
| Graph topology | Vertices/edges, Cypher traversal | — |
| Atlas unique/FTI shadow | `atlas_unique_key`, `atlas_fti_*` for now | **Optional** denorm later for bulk search |
| **Entity document store** | Hot path via AGE properties today | **`atlas.entity_doc`** (GUID, type, QN, props JSON) |
| **Classification membership** | Derived from AGE edges/props | **`atlas.entity_classifications`** (tag-based Ranger feed) |
| **Column sample / row checks** | — | **Data plane** (already Kudu tables) via FDW |
| Ranger policy admin | `x_policy*`, defs | — |
| Ranger **tag denorm** for plugins | `x_tag*` (when TagSync lands) | Optional **`ranger.tag_resource`** for Impala-side bulk |
| sigint sampling | Python ImpalaSampler today | **`gov.column_sample`** via FDW (SPEC) |

```
Postgres :5455
  ├─ AGE atlas_graph          (topology + Cypher; Aegir-loadable)
  ├─ Ranger admin schema      (policies; greenfield TagSync)
  ├─ signals_catalog          (HMS-free Impala registry)
  └─ impala_fdw
        ├─ impala_sql  → Impala HS2 → Kudu   (general SQL, samples)
        └─ kudu_scan   → libkudu_client       (pk_lookup, sample)  [NYI]
```

**Implication:** “Scale Atlas on pglite” means (a) keep Cypher thin, (b) put **high-volume entity/tag tables** on Kudu when PG heap + FTI become the bottleneck, (c) accelerate **tagging/policy** by sampling and denormalized tag tables over FDW—not by relocating AGE.

---

## 2. FDW operational coverage audit (vs SPEC + Atlas)

### 2.1 What works now (phase ~1)

| Capability | Status | Atlas/Ranger relevance |
|------------|--------|------------------------|
| Extension load / options | ✅ | Server + foreign tables |
| HS2 NOSASL connect/execute/fetch | ✅ | Data samples, smoke |
| Full-table / projected SELECT | ✅ | Column sample (unbounded path) |
| Impala identifier quoting (backticks) | ✅ | Required for Impala SQL |
| HMS-free Kudu access type READWRITE | ✅ | CREATE + SELECT after catalogd reload |
| GetOperationStatus wait (DML/async) | ✅ | Needed if FDW ever writes; UPSERT via tools |
| `fdw_smoke` e2e via PG | ✅ | Path proof |
| Path selector stub | ⚠️ | Classifies pk/limit but **always falls back to HS2** |
| Kerberos HS2 | ❌ | Product identity; Ranger needs real principal |
| Postgres GSSAPI session → outbound principal | ❌ | SPEC S1–S2 |
| libkudu_client / `kudu_scan` | ❌ | **Critical** for Atlas pk_lookup latency |
| Predicate / LIMIT pushdown | ❌ | Samples still full remote SELECT |
| EXPLAIN AccessMethod / ShapeId | ❌ | Observability for gov shapes |
| IMPORT FOREIGN SCHEMA | ❌ | Bulk expose Atlas-side tables |
| Session pool | ❌ | Atlas bulk ops will thrash connect |
| DML via FDW | ❌ (SPEC N3) | Atlas writes stay REST/AGE; data plane DDL via Impala |

### 2.2 SPEC §6 governance shapes × Atlas/Ranger callers

| Shape ID | Preferred | Implemented | Primary consumer |
|----------|-----------|-------------|------------------|
| `gov.pk_lookup` | kudu_scan | HS2 only (fallback) | AGE enrich, entity hydrate by GUID/QN |
| `gov.unique_lookup` | kudu_scan | — | `qualifiedName` / business key |
| `gov.filtered_scan` | kudu_scan (sel.) | full scan HS2 | Policy preview, tag membership filter |
| `gov.column_sample` | kudu_scan | HS2 full SELECT | **sigint Tagger** (replaces ImpalaSampler long-term) |
| `gov.projection_only` | impala_sql | HS2 SELECT * cols | Feature extract |
| `gov.schema` | metadata | — | IMPORT / describe |
| `sql.general` | impala_sql | HS2 | Ad-hoc, joins local in PG |

**Gap summary for Atlas acceleration:** without **pushdown + kudu_scan + pooling**, every AGE-adjacent join to a foreign table pays HS2 session + full scan. That does not scale for bulk classification (thousands of columns × sample).

### 2.3 Code reality (impala_fdw.c)

- Builds `SELECT col… FROM db.table` only—**no WHERE, no LIMIT**.
- `impala_fdw_select_path(..., has_limit=false, quals_are_pk_eq=false)` hard-coded; planner does not feed quals yet.
- Explicit comment: kudu_scan not implemented → force impala_sql.

### 2.4 Atlas AGE hot paths (today on PG)

From `AgeSchemaManager` / live DB (`atlas_graph`, ~627 vertices in this devenv):

| Op | Mechanism | Index |
|----|-----------|--------|
| getVertex(id) | AGE id() | `idx_vertex_ageid` |
| Lookup by `__guid` | property access | `idx_vertex_guid` |
| Lookup by `qualifiedName` | property access | `idx_vertex_qn` |
| Unique attribute | `atlas_unique_key` | PK (key_name, key_value) |
| FTS | `atlas_fti_vertex.search_text` | tsvector |
| Composite index | `atlas_composite_index` | multi-col PK |
| Classification names | props / FTI trigger | text concat on write |

Aegir-scale sample will inflate **vertex heap + unique_key + fti** write amplification on PG. That is the scale pressure to offload **document/tag denorms** to Kudu—not Cypher.

### 2.5 Ranger greenfield touchpoints

| Piece | Needs from FDW / Kudu |
|-------|------------------------|
| TagSync Atlas → Ranger | Atlas REST (not FDW); optional **read** denorm table on Kudu for offline audit |
| Impala plugin | Sees **Kerberos principal** from query path; FDW S2/S3 identity |
| Tag-based mask/filter | Tags on Atlas entities; **enforcement** on Impala against **Kudu data tables** |
| Policy test harness | FDW SELECT sample rows under different PG/KRB users (RLS + Ranger) |

FDW does **not** evaluate Ranger policies (SPEC N7). It must not collapse identity to a shared service account when Ranger is on.

---

## 3. Kudu-optimal schema (Atlas + AGE support)

Design for **point get + tag filter + time-bounded sample**, HASH on high-cardinality keys, RANGE only when time retention matters.

### 3.1 Data plane (already the tagging input)

Existing Impala/Kudu tables (workload tables) stay as-is; Tagger samples via FDW:

```sql
-- Pattern for sampled tables (example)
CREATE TABLE gov_probe (
  id BIGINT PRIMARY KEY,
  ...
) PARTITION BY HASH (id) PARTITIONS 2 STORED AS KUDU;
```

- **PK = natural/business key** when point lookups matter; else surrogate + unique secondary in registry.
- Prefer **HASH(PK)** for even tablet load; avoid RANGE on GUID strings.
- Column sample does not need range partitions.

### 3.2 Atlas denormalized store on Kudu (phase proposal)

```sql
-- Entity document (bulk get / list by type)
CREATE TABLE atlas.entity_doc (
  guid            STRING PRIMARY KEY,          -- Atlas __guid
  type_name       STRING NOT NULL ENCODING RLE,
  qualified_name  STRING NOT NULL,
  service_type    STRING ENCODING RLE,
  state           STRING ENCODING RLE,         -- ACTIVE/DELETED
  modified_time   BIGINT,                      -- epoch ms
  properties_json STRING                       -- compact JSON; or split hot attrs
) PARTITION BY HASH (guid) PARTITIONS 8
  STORED AS KUDU
  TBLPROPERTIES ('kudu.num_tablet_replicas'='1');  -- devenv; 3 in prod

-- Secondary unique projection for QN lookup (write path dual-updates)
CREATE TABLE atlas.entity_by_qn (
  qualified_name  STRING PRIMARY KEY,
  guid            STRING NOT NULL,
  type_name       STRING ENCODING RLE
) PARTITION BY HASH (qualified_name) PARTITIONS 8
  STORED AS KUDU;

-- Classification membership (Ranger TagSync / policy helpers)
CREATE TABLE atlas.entity_classifications (
  guid              STRING,
  classification    STRING,          -- SIGDG CURIE or Atlas type name
  propagate         BOOLEAN,
  applied_time      BIGINT,
  PRIMARY KEY (guid, classification)
) PARTITION BY HASH (guid) PARTITIONS 8
  STORED AS KUDU;

-- Invert for "all entities with tag X" (Ranger / search)
CREATE TABLE atlas.classification_entities (
  classification    STRING,
  guid              STRING,
  type_name         STRING ENCODING RLE,
  PRIMARY KEY (classification, guid)
) PARTITION BY HASH (classification) PARTITIONS 4
  STORED AS KUDU;
```

**Why this shape:**

| Access | Table | Kudu path |
|--------|-------|-----------|
| Entity by GUID | `entity_doc` | `gov.pk_lookup` |
| Entity by QN | `entity_by_qn` → guid → doc | unique_lookup |
| Tags on entity | `entity_classifications` | pk prefix / filtered_scan |
| Entities by tag | `classification_entities` | pk prefix (classification=) |
| Cypher lineage | AGE only | no Kudu |

**Partitioning rules:**

1. **HASH(high-cardinality PK)** for tablet balance (guid, qn).
2. **Do not RANGE-partition GUIDs** (random → hotspot free but useless ranges).
3. If audit retention needed, **RANGE(applied_time)** only on a separate audit table, not the hot membership PK.
4. **RLE** on low-cardinality STRING columns (`type_name`, `classification` family).
5. **PARTITIONS ≈ 2–4× tservers** for lab; scale with cluster size, not entity count blindly.
6. HMS-free: register in `signals_catalog` + set access type READWRITE on load (already fixed).

### 3.3 AGE remains graph spine

Keep on PG:

- `atlas_graph.vertex` / edges (topology)
- Thin edges: `__guid` edges for lineage/process
- Sync **writer path**: Atlas REST/AGE write → async dual-write or outbox → Kudu denorm (not FDW DML in v1)

Aegir sample should stress both:

1. AGE vertex/edge volume (Cypher correctness)
2. Kudu denorm row count (FDW `pk_lookup` / tag invert)

### 3.4 Ranger (greenfield) Kudu-facing tables (optional)

Only after TagSync exists; Impala plugin normally uses Ranger’s admin store. If bulk tag evaluation needs offline tables:

```sql
CREATE TABLE ranger.tag_resource (
  resource_service  STRING,
  resource_path     STRING,   -- db.table.column
  tag_type          STRING,
  tag_attributes    STRING,   -- JSON
  PRIMARY KEY (resource_service, resource_path, tag_type)
) PARTITION BY HASH (resource_path) PARTITIONS 8
  STORED AS KUDU;
```

Prefer TagSync → Ranger DB as source of truth; Kudu mirror is for **analytics / dual-path demos**, not a second policy engine.

---

## 4. Priority roadmap (Atlas-first, Ranger second)

| Priority | Work | Unlocks |
|----------|------|---------|
| **P0** | Predicate + LIMIT pushdown on `impala_sql` | Usable `gov.column_sample` for Tagger via FDW |
| **P0** | HS2 session pool | Bulk entity/sample without connect storm |
| **P1** | `libkudu_client` + `gov.pk_lookup` / `column_sample` | Latency for GUID/QN hydrate at Aegir scale |
| **P1** | EXPLAIN ShapeId + path metrics | Prove selector; regression |
| **P1** | Dual-write or bridge: Atlas entity apply → Kudu denorm | Scale reads off AGE heap |
| **P2** | Kerberos S1–S2 (PG GSS + HS2 same principal) | Ranger-ready identity |
| **P2** | IMPORT FOREIGN SCHEMA + catalog registry | Ops ergonomics |
| **P3** | Ranger TagSync + Impala plugin | Tag enforcement on Kudu data |
| **P3** | RLS / barrier views over foreign tables | PG-side governance roles |
| Later | Invert classification table + search | Tag-centric Ranger helpers |

---

## 5. Aegir sample guidance

When generating Atlas sample via Aegir:

1. **Entity mix:** hive_db / hive_table / hive_column (current types) → migrate names later; include SIGDG classifications on columns.
2. **QN convention:** `db.table@cluster` / `db.table.col@cluster` stable for `entity_by_qn`.
3. **Scale tiers:** 1k / 10k / 100k entities; measure (a) AGE getVertex, (b) Kudu pk_lookup via FDW, (c) tag invert count.
4. **Do not** generate only AGE-heavy graphs without denorm rows—FDW won’t be exercised.
5. Keep lineage edges in AGE; store process inputs/outputs as edge labels (already present as `__type_edge_Process_*`).

---

## 6. Conclusions

1. **FDW is correctly scoped** as the governance **data plane** adapter (SPEC consumers: AGE, Ranger helpers, sigint)—not a replacement for Atlas REST or AGE Cypher.
2. **Operational coverage for Atlas is thin today:** HS2 full-scan only; the closed algebra that would accelerate Atlas/tagging (`pk_lookup`, `column_sample`) is stubbed.
3. **Scale path:** AGE topology on PG; **entity/tag denorm + samples on Kudu**; FDW pushdown + kudu_scan + pooling before Aegir-scale is meaningful.
4. **Kudu schema:** HASH on GUID/QN; dual tables for entity doc vs classification invert; RLE low-cardinality; no GUID range partitions.
5. **Ranger:** identity (Kerberos principal through FDW/Impala) and TagSync first; optional Kudu tag mirror later—not FDW policy evaluation.
