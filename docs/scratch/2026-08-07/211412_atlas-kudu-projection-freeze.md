# Freeze: Atlas typed Kudu projections + FDW gates

**Status:** FROZEN for implementation  
**Supersedes:** earlier denorm sketches; incorporates critique + six pre-freeze sharpenings.

---

## 1. First principles (binding)

1. **Do not** mirror AGE `(graphid, agtype)` into Kudu.
2. **AGE** = transactional graph of record (topology, Cypher, single-entity tag UI).
3. **Kudu** = typed, flattened projections keyed by access path (derived layer).
4. **Sync** = outbox / notification → Impala/Kudu client **UPSERT** (and ordered DELETE/INSERT for mutable keys). **Not** multi-row TX. **Not** FDW DML as SoR or primary writer.
5. Kudu advantages used deliberately: strongly typed columns, columnar encoding; **no** schemaless simulation of structured data as the primary model.

### Explicitly out of Kudu

- Fulltext / tsvector (`atlas_fti_*` stays on PG)
- Type-system / relationshipType catalog (tiny, AGE-native)
- Per-label physical edge tables (label explosion)
- Cross-entity multi-row atomicity

### Explicitly out of FDW (v1)

- DML as product write path (SPEC N3)
- Ranger / policy evaluation inside the FDW
- Hosting AGE Cypher storage

---

## 2. Projection tables

### 2.1 `entity_flat` — hydrate + DSL hot attrs

```sql
CREATE TABLE entity_flat (
  guid BINARY NOT NULL,              -- 16-byte UUID, plain encoding
  type_name STRING NOT NULL,         -- dictionary / RLE
  qualified_name STRING,             -- not PK; mutable; display + spill for rare filters
  name STRING,
  state INT8,
  created_ts UNIXTIME_MICROS,
  updated_ts UNIXTIME_MICROS,        -- mutable; never partition key
  props_json STRING,                 -- COLD attributes only; size-capped
  PRIMARY KEY (guid)
) PARTITION BY HASH (guid) PARTITIONS <2–3× tservers>
  STORED AS KUDU;
```

- HASH on **guid**, never `type_name` (hive_column skew).
- Type-scoped search: fan-out all tablets; dictionary predicate on `type_name` nearly free.
- **Hot column list frozen at implement time** (minimum: guid, type_name, qualified_name, name, state, timestamps). Search-critical fields must not live only in `props_json`.

### 2.2 `entity_by_qn` — secondary index for exact QN resolution

Kudu has no secondary indexes; **this table is the secondary index**.

Atlas unique attributes are **scoped per type** — two entities of different types may legally share a `qualifiedName` string. Digest must be:

```text
qn_digest = H( type_name ‖ separator ‖ qualified_name )
```

not `H(qualified_name)` alone (silent collisions).

```sql
CREATE TABLE entity_by_qn (
  qn_digest BINARY NOT NULL,        -- fixed-width (e.g. 16B); NOT full QN string
  guid BINARY NOT NULL,
  type_name STRING NOT NULL,         -- denorm for debug / dual-check
  PRIMARY KEY (qn_digest)
) PARTITION BY HASH (qn_digest) PARTITIONS N
  STORED AS KUDU;
```

- Long QN never in PK (composite key size + encoding).
- Full QN remains a regular column on `entity_flat`.

#### Mutability + ordering invariant (hard)

`qualifiedName` (and type in rare cases) is **mutable**. A rename is:

```text
DELETE entity_by_qn WHERE qn_digest = digest(old_type, old_qn);
INSERT/UPSERT entity_by_qn (digest(new_type, new_qn), guid, ...);
-- plus UPSERT entity_flat with new qualified_name
```

Idempotent latest-state UPSERT alone is **insufficient** for `entity_by_qn` under retries:

- Retried DELETE after INSERT → dangling/missing mapping.
- Kudu has no conditional/versioned writes; Impala UPSERT cannot compare versions.

**Correctness invariant (freeze):**

> Per-key **ordered delivery** in the outbox pipeline (e.g. Kafka partition key = `guid` for entity mutations, edge PK for edge mutations).  
> At-least-once delivery is safe **only** under per-key order for latest-state upserts **and** for delete+insert pairs on mutable secondary keys.

Put this in sync design and CI assumptions; do not treat it as a nicety.

### 2.3 Adjacency — one table per direction

**Impala HS2 constraint (2026-08-07):** Kudu **BINARY** columns cannot be used in Impala scan predicates
(`IllegalStateException: Unsupported Kudu type considered for predicate: BINARY`).
For the **impala_sql** path, adjacency keys are **fixed 32-char hex STRING** (`signals.guid_encoding=hex32`).
Logical key is still 16-byte guid; `libkudu_client` may use BINARY later without changing identity.

```sql
CREATE TABLE edge_out (
  src STRING NOT NULL,              -- hex32 of guid (HS2-pushable)
  elabel STRING NOT NULL,
  dst STRING NOT NULL,
  dst_type STRING,                   -- denorm for type-pruned expand
  PRIMARY KEY (src, elabel, dst)
) PARTITION BY HASH (src) PARTITIONS N
  STORED AS KUDU;

CREATE TABLE edge_in (
  dst STRING NOT NULL,
  elabel STRING NOT NULL,
  src STRING NOT NULL,
  src_type STRING,
  PRIMARY KEY (dst, elabel, src)
) PARTITION BY HASH (dst) PARTITIONS N
  STORED AS KUDU;
```

- Single `elabel` STRING column (dictionary), **not** one table per Atlas edge type.
- Every AGE edge mutation → two Kudu writes (out + in); deletes need full edge identity (see §4).

### 2.4 Classification assignments — skew-aware (single table default)

```sql
CREATE TABLE entity_classifications (
  tag_name STRING NOT NULL,
  guid BINARY NOT NULL,
  propagate BOOLEAN,
  applied_time UNIXTIME_MICROS,      -- or BIGINT ms; freeze at implement
  PRIMARY KEY (tag_name, guid)
) PARTITION BY HASH (guid) PARTITIONS N
  STORED AS KUDU;
```

| Query | Behavior |
|-------|----------|
| Entities with tag T | All tablets; PK prefix `(T, *)` |
| Tags on one guid | One tablet (HASH guid); column filter on guid within tablet |

**Mirror `PRIMARY KEY (guid, tag_name)`: default NO.**

- “Open entity → show tags” for a single entity is **AGE’s job** (SoR, transactional, few rows).
- Only revisit a guid-leading mirror if **batch tag hydration of search result pages** (IN-list on many guids) multiplies one-tablet filter cost in production metrics.
- Do not pay 2× classify write amp preemptively.

### 2.5 Entity audit — multilevel (HBase-shaped)

```sql
CREATE TABLE entity_audit (
  guid BINARY NOT NULL,
  event_ts UNIXTIME_MICROS NOT NULL,  -- immutable, monotonic
  seq INT64 NOT NULL,                 -- tie-break within ts
  -- event payload columns (typed) + optional cold json
  PRIMARY KEY (guid, event_ts, seq)
) PARTITION BY HASH (guid) PARTITIONS H,   -- lab: small H (2–4)
  RANGE (event_ts)                         -- monthly rolling window
  STORED AS KUDU;
```

- RANGE only because `event_ts` is immutable/monotonic.
- Retention = `DROP RANGE PARTITION` (compaction-friendly discard).
- Tablet product = hash × ranges; keep H modest on lab.

**1.17+ flexible / per-range hash:** lab can run 2 hash buckets on all months; prod can raise hash only on **future** high-volume ranges without rewriting history. That is the sizing escape hatch—do not pick one lifetime hash for audit under growth.

---

## 3. Traversal engine (named decision)

### Not: `WITH RECURSIVE` joined to a foreign table

A recursive CTE over a foreign table will **not** reliably deparse to a single IN-list remote scan. The planner tends toward:

- per-row parameterized remote scan (fatal at scale), or  
- no useful pushdown.

### Yes: procedural frontier loop

```text
frontier = seed guids
for depth in 1..max_depth:
  for chunk in chunks(frontier, B):   -- B ~ 256–1024 (measure)
    next = SELECT dst, elabel FROM edge_out
           WHERE src = ANY($1::bytea[])   -- or literal IN-list
    dedup into visited; frontier = next \ visited
  stop on budget / empty
hydrate = SELECT … FROM entity_flat WHERE guid = ANY($result::bytea[])
```

**Phase-1 FDW test suite must include both plan shapes:**

1. Literal `IN (...)`  
2. `= ANY(array)` / `src = ANY($1::bytea[])`  

They are different plan shapes; only testing literals leaves the traversal engine broken.

Depth **> ~5** impact analysis may later want a **materialized TC** table—but **only after measuring hop cost with real IN/ANY pushdown**. Frontier loop may be fast enough that TC write amp on every lineage edge never pays. Hold that line.

---

## 4. Sync / delete decoding (prerequisite)

### Outbox sources

Prefer **Atlas notification stream** (full payloads) when available.

If **logical decoding** of AGE label tables is used:

- Default DELETE replica identity often emits **only pkey (`graphid`)** — not `(src, elabel, dst)`.
- Kudu two-sided edge delete **requires** full edge identity.

**Decide before wiring sync:**

| Option | Action |
|--------|--------|
| A | `REPLICA IDENTITY FULL` on AGE edge label tables that feed the outbox |
| B | Source deletes from Atlas notification stream with full edge payload |
| C | Hybrid: notifications for graph mutates; decoding only for entities with full row |

Do not discover orphaned `edge_out`/`edge_in` rows after go-live.

### Per-key order (repeat)

Kafka (or equivalent) partition key:

- Entity mutations → `guid`
- Edge mutations → stable edge id / `(src, elabel, dst)` bytes
- Classification → `(guid)` or `(tag_name, guid)` consistently

---

## 5. FDW phase-1 exit criteria (Atlas projection path)

Must ship for this design to be non-decorative:

| Gate | Why |
|------|-----|
| Column projection | Avoid fetching `props_json` on every scan |
| Equality / range on PK prefixes | Point get, tag prefix, audit bounds |
| **Literal IN-list pushdown** | Frontier expand |
| **`= ANY(array)` deparse + pushdown** | Frontier expand (procedural) |
| `kudu_scan` for these tables (or proven HS2 only for lab) | Latency; prefer kudu_scan |
| EXPLAIN shows AccessMethod + ShapeId | Regression |
| Session pool if any HS2 fallback | Bulk |

DML via FDW remains out of scope for product writes; sync uses Impala UPSERT / native Kudu client out-of-process.

Promote SPEC §8.1 IN-list from “optional phase 2” to **phase-1/3 exit** for Atlas projection work.

---

## 6. Freeze checklist

- [x] AGE SoR; Kudu derived; no agtype layout mirror  
- [x] Tables: `entity_flat`, `entity_by_qn` (type‖QN digest), `edge_out`, `edge_in`, `entity_classifications` (tag-leading PK, HASH guid), `entity_audit` (HASH×RANGE)  
- [x] Classification guid-leading mirror: **default no**  
- [x] props_json cold-only + explicit hot column list  
- [x] Per-key ordered outbox (mutable QN = DELETE+INSERT under order)  
- [x] Delete payload strategy: REPLICA IDENTITY FULL and/or Atlas notifications — **decided before sync wire**  
- [x] Traversal = frontier loop, not recursive CTE over FDW  
- [x] FDW tests: literal IN + ANY(array)  
- [x] Audit hash flexible per range (1.17+); lab small H  
- [x] TC only after measured hop cost with pushdown  
- [x] Fulltext / type catalog / per-label edge tables stay out of Kudu  
- [x] FDW DML not product write path  

---

## 7. Next work (not frozen schema)

**Frontier batching numbers** — measure:

- batch size B vs hop latency  
- FDW deparse cost (IN vs ANY)  
- hydrate cost after N hops  
- whether depth-5 impact analysis stays under SLO without TC  

That measurement decides if a transitive-closure table ever exists.
