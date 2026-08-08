# Critique: typed Kudu projections for Atlas (not AGE layout)

Critique of the proposed four-table design (entity_flat, edge_out/in, classification, audit) before implementation.

---

## Verdict

The **first decision is right and binding**: do not mirror `(graphid, agtype)` into Kudu. AGE remains the transactional graph of record; Kudu holds **typed, access-path-keyed projections** fed by **idempotent UPSERTs**. That matches Kudu’s strengths, Atlas hot paths, and the FDW’s closed algebra.

Three refinements are worth locking before build:

1. **qualifiedName point lookup** needs an explicit secondary access path (not only `entity_flat` HASH(guid)).
2. **Classification table** as specified is excellent for “entities by tag”; “tags by entity” is a one-tablet filtered scan—document or add a thin reverse if that ratio is hot.
3. **IN-list pushdown** is not optional for this design—it is a hard dependency of recursive adjacency; SPEC currently lists it as phase-2 optional, which must be promoted.

---

## What is strongly correct

### Non-mirroring AGE

- Columnar encoding + typed columns are the point of Kudu; `props_json` as **cold spillover** is the right exception, not the schema.
- Immutable PK + UPSERT-as-sync is the right consistency posture for a **derived** layer (no multi-row TX, no PK mutation).
- Hash on **guid**, never on `type_name` (hive_column skew).

### entity_flat

- BINARY 16-byte UUID, plain encoding: good for PK density and fixed width.
- Dictionary/RLE-friendly `type_name` for fan-out type filters after hash prune.
- Mutable `updated_ts` **out of partitioning**: correct and easy to get wrong.

### Dual adjacency

- Separate `edge_out` / `edge_in` with HASH on the join side is the right model for one-hop expand.
- Recursive frontier as **batched IN-list on hashed column** is the only way hash pruning works; “IN-list optional” in the FDW SPEC is incompatible with this design.

### Classification skew trick

```text
PRIMARY KEY (tag_name, guid)
PARTITION BY HASH (guid)
```

- Writes stay uniform (hash guid).
- “All PII” = all tablets × tight PK prefix `(tag_name=PII, …)`.
- Hashing on `tag_name` would hot-spot; correctly rejected.

### Multilevel audit

- Classic metrics pattern; only place RANGE belongs in this set.
- Month partitions + `DROP RANGE PARTITION` for retention is the right answer to tombstone/compaction pain.
- Tablet math (hash × months) must stay modest—call out **hash buckets on audit < entity_flat**.

### Sync

- Logical decoding / Atlas notification → outbox → UPSERT is the right shape.
- At-least-once + idempotent keys fits Kudu; do not invent 2PC across AGE and Kudu.

### FDW pushdown triad

Projection, PK-prefix (eq/range), IN-list—exactly the three that make this pay. Without them the design is paper.

---

## Pushbacks and refinements

### 1. qualifiedName is a first-class Atlas access path

Atlas/AGE already index `qualifiedName` and `__guid` as first-class lookups. `entity_flat` PK = guid covers hydrate-by-id; **DSL/basic search and catalog bridge often key by QN**.

With only HASH(guid):

- `WHERE guid = ?` → one tablet, perfect.
- `WHERE qualified_name = ?` → **all tablets**, column predicate (or full scan of projected columns).

That is fine for rare admin queries; it is not fine if QN is on the hot path.

**Recommendation:** keep a thin secondary table (or accept a fixed-width digest as alternate):

```sql
CREATE TABLE entity_by_qn (
  qn_hash BINARY NOT NULL,       -- 16B hash of qualifiedName (or full QN if short + digest)
  guid BINARY NOT NULL,
  PRIMARY KEY (qn_hash)
) PARTITION BY HASH (qn_hash) PARTITIONS N;
-- store full qualified_name on entity_flat only (not in this PK if long)
```

Or store `qn_hash` on `entity_flat` and maintain a unique secondary— but Kudu has no secondary indexes, so the **second table is the secondary index**. Do not put long QN strings in the PK (16KB composite limit + variable encoding).

### 2. Classification: entity→tags vs tag→entities

As designed:

| Query | Behavior |
|-------|----------|
| Tags for one `guid` | HASH prune to 1 tablet; within tablet PK order is `(tag_name, guid)` → **column filter** on guid (not PK prefix). Still one tablet—usually OK. |
| Entities for one `tag_name` | All tablets; PK prefix scan per tablet—by design. |

If “open entity → list classifications” is as hot as “search by tag”, document the one-tablet filter cost, or add:

```sql
PRIMARY KEY (guid, tag_name)  -- HASH(guid)  -- mirror for entity-centric reads
```

Dual membership tables = 2× write amp on classify; often worth it for Atlas UI.

### 3. Adjacency write path and labels

- Every AGE edge mutation → **two** UPSERTs (out + in). Outbox must be per-edge with stable keys; delete = UPSERT tombstone or explicit DELETE if Impala/Kudu path allows.
- Atlas edge labels are many (`__type_edge_*`, composition, lineage). Keep `elabel` as STRING with dictionary encoding; do **not** create one physical table per label (label explosion).
- `dst_type` on the edge row is a good denorm for type-pruned expand without joining `entity_flat` on every hop.

### 4. Recursive traversal cost in Postgres

`WITH RECURSIVE` + FDW hop per layer:

- Each hop = planner + remote scan(s); batch IN-lists aggressively (e.g. 256–1024 ids).
- Cap depth and width; lineage impact analysis at depth > 5 may need **materialized TC** (you flagged this correctly as the next bottleneck).
- Prefer **kudu_scan** for hop tables; HS2 per hop will not survive Aegir-scale graphs.

### 5. props_json discipline

Treat as:

- Explicit **hot column list** for DSL (name, state, owner, qualified_name, type_name, timestamps).
- Spill only true cold/rare attributes; size-cap JSON; never put search-critical fields only in JSON.

Otherwise you reintroduce “schemaless Kudu” by habit.

### 6. GUID representation and join with AGE

- AGE uses `graphid` + string `__guid` in properties; Kudu uses 16-byte BINARY.
- Sync layer owns encode/decode; FDW maps BINARY → `bytea`; application/Cypher joins use **string GUID in PG** vs **bytea on foreign table**—document conversion functions so recursive SQL does not cast incorrectly.
- Prefer storing Atlas `__guid` as UUID bytes (canonical), not graphid (AGE-internal, not portable).

### 7. Audit tablet explosion

8 hash × 36 months = 288 tablets **from one table**. On a small devenv/lab cluster that is heavy next to entity_flat’s N and two edge tables.

- Lab: HASH 2–4 on audit, monthly ranges as needed.
- Prod: size hash so total tablets stay within ops comfort (~tens–low hundreds per table), not thousands.

### 8. FDW phase order forced by this design

| Must land early | Why |
|-----------------|-----|
| Column projection | Avoid fetching props_json |
| Eq / range on PK prefixes | Point get, tag prefix, audit time bounds |
| **IN-list** | Recursive edge expand |
| kudu_scan for these tables | Latency; HS2 session per hop is fatal |
| Session pool (if any HS2 fallback) | Bulk |

SPEC §8.1 “IN optional phase 2” → **promote to phase 1/3 exit criteria** for Atlas projection work.

DML via FDW still out of scope for v1: sync writers use Impala UPSERT / Kudu client out-of-process, not foreign INSERT.

### 9. What not to put in Kudu

- Fulltext / tsvector (stay on `atlas_fti_*` in PG until a dedicated search path exists).
- Type-system / relationshipType catalog (tiny, AGE-native).
- Cross-entity multi-row atomicity (Atlas REST + AGE TX remains SoR).

---

## Optional next layers (when measured)

### Transitive closure (impact analysis)

If recursive hops dominate:

```sql
-- reachability or depth-limited TC
PRIMARY KEY (src, dst, elabel_family)  -- or include depth
HASH (src)
```

Trade: write amp on every edge change (recompute or incremental). Only after measuring hop cost with IN-list FDW.

### Traversal batching strategy (sketch)

1. Seed frontier GUIDs (bytea) from AGE or entity_flat.
2. Chunk to B ids; `SELECT dst, elabel FROM edge_out WHERE src IN (...)` with pushdown.
3. Dedup in PG; stop at depth/budget.
4. Final hydrate: `entity_flat WHERE guid IN (result_set)`—again IN-list + projection of hot cols only.

---

## Alignment with prior audit

Earlier audit proposed entity_doc + entity_by_qn + dual classification tables. This proposal is **stricter and better** on:

- BINARY guids, no type-hash skew, dual edge tables, multilevel audit, classification sort/hash split.

Adopt this proposal as the baseline, with the **QN secondary table** and **IN-list as non-optional** amendments.

---

## Suggested freeze list before implementation

1. AGE = SoR; Kudu = derived projections; sync = UPSERT/outbox.
2. Four core tables + **entity_by_qn** (or equivalent).
3. HASH(guid) for entity/edges/class; HASH(guid)×RANGE(event_ts) only for audit.
4. Hot attrs explicit; props_json cold only.
5. FDW: projection + PK predicates + IN-list + kudu_scan for these shapes.
6. Aegir load exercises both AGE Cypher and Kudu denorm paths.
7. Ranger later: read classification projection; enforce on Impala with real principals—not FDW policy.

Ready to go deeper next on **frontier batching** or **TC table** when you want to nail hop latency numbers rather than schema.
