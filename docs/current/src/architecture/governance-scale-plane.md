# Governance scale plane (Atlas / Ranger / Kudu / RustFS)

**Why this exists:** Federated engine services (Ægir, Atelier, Gaius, Hermes
plugins, discovery traffic) cannot all pound Postgres+AGE (“pglite” colloquial
for the lab governance DB on `:5455`) for bulk entity, tag, lineage, and object
work. **Kudu** is the high-throughput store for **derived** governance tables;
**RustFS** is the durable **object** store on `$SIGNALS_DATA_ROOT/rustfs`.  
**Postgres+AGE remains the thin SoR** for topology, policy admin, and Cypher.

This is a **prerequisite** for healthy multi-engine operation and for
[signals-protocol](./signals-protocol-core.md) work that multiplies concurrent
clients.

## Split of authority

| Plane | Store | Holds | Not for |
|-------|-------|-------|---------|
| **Topology SoR** | Postgres + AGE (`atlas_graph`, `signals_ol`) | Vertices/edges, Cypher, hot single-entity paths | Bulk scans, multi-engine fan-out |
| **Policy admin SoR** | Postgres `ranger` DB | `x_policy*`, defs, admin UI | High-QPS tag membership scans |
| **Governance projections** | **Kudu** DB `atlas` (+ `ranger` projections) | entity_flat, by_qn, edges, classifications, audit; Ranger tag denorm | openCypher graph |
| **Object / blob** | **RustFS** under `$SIGNALS_DATA_ROOT/rustfs` | artifacts, lineage packages, Weathership memory blobs, backup objects | Relational keys |
| **Logical packages** | DataFusion (`signals-df`) over Parquet | portable backup/verify/SQL | Live multi-writer SoR |

```text
Federated engines / Hermes
        │ discovery + REST/gRPC
        ▼
  Signals gateways (Atlas :21010, Ranger :6080, S3 :9010)
        │
        ├─ thin write / Cypher ──► Postgres :5455 + AGE
        │                              │ outbox / notification (sync)
        │                              ▼
        ├─ bulk read / tag join ──► Kudu (atlas.*, ranger.*) via Impala/FDW
        │
        └─ objects ───────────────► RustFS ($SIGNALS_DATA_ROOT/rustfs)
```

**Hard rule:** Do **not** relocate AGE openCypher onto Kudu. See historical
audit `docs/scratch/2026-08-07/204458_fdw-atlas-ranger-scale-audit.md`.

## Atlas → Kudu

| Artifact | Path |
|----------|------|
| DDL | `config/atlas/kudu_projections.sql` |
| FDW | `config/atlas/kudu_projections_fdw.sql` |
| Seed | `just atlas-kudu-projections-seed` |
| Outbox contract | [Atlas → Kudu outbox](./atlas-kudu-outbox.md) |

**Landed:** tables + FDW registration (phase 1a).  
**Still required for “fully leverage”:**

1. **Outbox worker** (Atlas notifications → Impala UPSERT) — at-least-once, per-key order  
2. True **`kudu_scan`** / libkudu_client for pk_lookup latency  
3. Federated engines **prefer FDW/Kudu projections** for bulk entity/tag reads  

Until the worker runs, projections are seedable but not continuously filled.

## Ranger → Kudu

| Artifact | Path |
|----------|------|
| DDL | `config/ranger/kudu_projections.sql` |
| FDW | `config/ranger/kudu_projections_fdw.sql` |
| Seed | `just ranger-kudu-projections-seed` |

**Admin SoR stays on Postgres** (`ranger` database). Projections hold
**tag↔resource denorm** and optional eval-friendly tables so Impala plugins and
engines do not scan `x_tag*` on PG under load.

Wire TagSync / notification → UPSERT after admin path is stable (greenfield
TagSync still near-term).

## RustFS (object store)

| Item | Value |
|------|--------|
| Data dir | `$SIGNALS_DATA_ROOT/rustfs` (default `/raid/signals/rustfs`) |
| S3 API | `http://127.0.0.1:9010` (`RUSTFS_ADDRESS`) path-style |
| Console | `http://127.0.0.1:9011` |
| Lab creds | `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` (override via secretspec) |
| Client | `mc` wrapper → alias `local` |
| Buckets (pre-created dirs) | `signals-artifacts`, `signals-lineage`, `weathership-memory`, `signals-backup` |
| Process | `processes.rustfs` (default stack) |
| Portable backup | existing `filesystem/rustfs` tar in `just backup` |

Port **9010** avoids collision with synth’s RustFS on **:9000** when co-hosted.

## Implications for signals-protocol

Discovery should advertise:

| kind | Example |
|------|---------|
| `ATLAS_GOVERNANCE` | `http://…:21010/api/atlas` |
| `LINEAGE_OL` | `http://…:21010/api/v1` |
| `RANGER_AUTHZ` | `http://…:6080` |
| `OBJECT_STORE` | `http://127.0.0.1:9010` (S3 path-style) |
| `GOV_PROJECTIONS` | Impala/FDW DSN or host hint for `atlas.*` / `ranger.*` Kudu |

Engines that need bulk governance **must not** openCypher-scan AGE for every
column sample. They use projections + object store, and leave SoR writes to
Atlas/Ranger APIs.

## Ops checklist

```bash
just bootstrap
devenv up -d
just atlas-kudu-projections-seed
just ranger-kudu-projections-seed
# RustFS: curl / mc against http://127.0.0.1:9010
mc ls local/
```

## Related

- [Atlas → Kudu outbox](./atlas-kudu-outbox.md)
- [Storage and backup](../operations/storage-and-backup.md)
- [Signals protocol core](./signals-protocol-core.md)
- [OpenLineage + Atlas](./openlineage-atlas.md)
