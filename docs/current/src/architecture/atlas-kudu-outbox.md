# Atlas → Kudu projection outbox contract

**Status:** Binding for sync implementers (freeze 2026-08-07).  
**SoR:** Postgres + AGE (`atlas_graph`).  
**Derived store:** Impala/Kudu tables in database `atlas` (see `config/atlas/kudu_projections.sql`).

## Goals

- Idempotent, at-least-once materialization of typed projections.
- Per-key ordered delivery so mutable secondary keys (`entity_by_qn`) stay correct.
- Full edge identity on delete so dual adjacency tables do not orphan rows.

## Topics / streams

| Stream | Partition key | Events |
|--------|---------------|--------|
| `atlas.entity` | `guid` (16-byte UUID or hex string of same) | create, update, soft-delete, QN/type rename |
| `atlas.edge` | stable edge id or `sha256(src‖elabel‖dst)` | create, delete |
| `atlas.classification` | `guid` | assign, remove tag |

Prefer **Atlas notification stream** (full payloads). Logical decoding is allowed only with the delete rules below.

## Per-key order (hard invariant)

Consumers **must** process events for a given partition key in order (single consumer per key, or Kafka partition = key).

At-least-once + Impala `UPSERT` is safe for **latest-state** entity_flat / classifications **only under this order**.

### Mutable `qualifiedName` (entity_by_qn)

Atlas unique attributes are **type-scoped**. Digest:

```text
qn_digest = first_16_bytes(SHA-256( type_name || 0x1F || qualified_name ))
```

(UTF-8; separator `0x1F` unit separator.)

Rename / type change on entity `G`:

```text
1. DELETE FROM atlas.entity_by_qn WHERE qn_digest = digest(old_type, old_qn)
2. UPSERT atlas.entity_by_qn (digest(new_type, new_qn), G, new_type)
3. UPSERT atlas.entity_flat (... new qualified_name, type_name ...)
```

A retried (1) after (2) without order → missing mapping. **Ordering prevents this;** Kudu has no conditional version compare on UPSERT.

## Entity mutations → Kudu

| AGE / Atlas change | Kudu ops |
|--------------------|----------|
| Create/update entity | `UPSERT entity_flat`; `UPSERT entity_by_qn` for current digest |
| QN or type_name change | Ordered DELETE old digest + UPSERT new digest + UPSERT flat |
| Soft delete / purge | DELETE/UPSERT tombstone policy (freeze: hard DELETE from projections or `state=DELETED` on flat only — pick one; default **state=DELETED** on flat + DELETE from by_qn and edges) |

Hot columns on `entity_flat` only: `guid`, `type_name`, `qualified_name`, `name`, `state`, `created_ts`, `updated_ts`. All other attributes → `props_json` (size-capped). Never put search-critical fields only in `props_json`.

Timestamps: store as **BIGINT microseconds since epoch UTC** (UNIXTIME_MICROS-compatible).

## Edge mutations → Kudu

| Change | Kudu ops |
|--------|----------|
| Create edge src -[:L]-> dst | `UPSERT edge_out (src,L,dst,dst_type)`; `UPSERT edge_in (dst,L,src,src_type)` |
| Delete edge | `DELETE` both sides with **full** `(src, elabel, dst)` |

### Delete decoding prerequisite

If using PostgreSQL logical decoding on AGE label tables:

- Default `REPLICA IDENTITY DEFAULT` emits only **pkey (`graphid`)** on DELETE — insufficient for Kudu.
- **Required before wiring:** either  
  - `ALTER TABLE … REPLICA IDENTITY FULL` on edge label tables feeding the outbox, **or**  
  - source deletes from Atlas notifications with full edge payload.

Do not ship sync without one of these.

## Classification mutations

| Change | Kudu ops |
|--------|----------|
| Assign tag T to guid G | `UPSERT entity_classifications (T, G, …)` |
| Remove tag | `DELETE` where `tag_name=T AND guid=G` |

No guid-leading mirror table by default (single-entity tag UI stays on AGE).

## Audit

Append-only: `UPSERT`/`INSERT` into `entity_audit` with `(guid, event_ts, seq)`.  
`event_ts` immutable monotonic; do not update. Retention via future RANGE partitions + `DROP RANGE PARTITION` (prod).

## Writers

| Allowed | Not allowed (v1) |
|---------|------------------|
| Impala HS2 UPSERT/DELETE from outbox worker | FDW INSERT/UPDATE/DELETE as SoR |
| Native Kudu client from worker | Multi-table 2PC with AGE |

## FDW consumers

Foreign tables: `config/atlas/kudu_projections_fdw.sql`.  
Traversal uses **frontier loop** + `src = ANY($1::bytea[])` pushdown — not recursive CTE over foreign tables.
