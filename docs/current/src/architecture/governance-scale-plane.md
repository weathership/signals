# Governance scale plane (Atlas / Ranger → pglite → FDW → Kudu)

**Why this exists:** Federated engine services (Ægir, Atelier, Gaius, Hermes)
must be able to run **simultaneously** without overwhelming the lab governance
database on Postgres `:5455` (colloquially **pglite** here: the thin AGE +
admin Postgres instance, not a separate product). Scale is achieved by
engineering **Atlas and Ranger to keep connecting to Postgres**, while
**Postgres uses impala_fdw** to reach **Kudu** for bulk governance tables.
**RustFS** holds durable objects on `$SIGNALS_DATA_ROOT/rustfs`.

This is a **prerequisite** for multi-engine operation and for
[signals-protocol](./signals-protocol-core.md).

## Primary path (remember this)

```text
  Atlas JVM  ── JDBC ──►  Postgres :5455  (DB signals + AGE atlas_graph / signals_ol)
  Ranger JVM ── JDBC ──►  Postgres :5455  (DB ranger — admin policies)
                              │
                              │  foreign tables (impala_fdw, Kerberos HS2 / kudu_scan)
                              │  atlas_entity_flat, ranger_tag_resource, …
                              ▼
                         Kudu  (atlas.* / ranger.* projection tables)
                              ▲
                              │ outbox / notification UPSERT (writers)
                         Impala HS2
```

| Layer | Role |
|-------|------|
| **Atlas / Ranger processes** | Always talk to **Postgres** (JDBC) — topology, admin, policy UI, Cypher |
| **Postgres (pglite)** | Thin **SoR** for AGE graph + Ranger admin; **FDW client** for scale reads |
| **impala_fdw** | How pglite **leverages Kudu** without relocating Cypher or policy admin |
| **Kudu projections** | High-volume **derived** entity/tag/edge/audit tables |
| **RustFS** | Object/blob store (not relational keys) |

**Hard rule:** Do **not** host AGE openCypher topology on Kudu. Do **not** make
engines bypass Postgres for Atlas/Ranger identity — they use Atlas/Ranger APIs
(or SQL against pglite, which FDWs to Kudu). Historical audit:
`docs/scratch/2026-08-07/204458_fdw-atlas-ranger-scale-audit.md`.

```text
Federated engines / Hermes
        │ discovery + REST / gRPC
        ▼
  Atlas :21010  /  Ranger :6080  /  S3 :9010
        │                │              │
        │ JDBC           │ JDBC         │ objects
        ▼                ▼              ▼
     Postgres :5455 (pglite)         RustFS
        │  AGE SoR + Ranger admin    ($SIGNALS_DATA_ROOT/rustfs)
        │  + foreign tables
        ▼
     Kudu (scale projections via FDW)
```

Bulk governance SQL from tools that sit **on** pglite (Aegir, analytics,
Weathership helpers) should hit **foreign tables** → Kudu, not sequential
openCypher over the whole estate.

## Split of authority

| Plane | Store | Holds | Not for |
|-------|-------|-------|---------|
| **Topology SoR** | Postgres + AGE | Vertices/edges, Cypher, hot single-entity paths | Bulk multi-engine scans |
| **Policy admin SoR** | Postgres `ranger` | `x_policy*`, defs, admin UI | High-QPS tag membership heap scans |
| **Scale projections** | **Kudu**, exposed as **PG foreign tables** | entity_flat, by_qn, edges, classifications; Ranger tag denorm | openCypher graph |
| **Object / blob** | **RustFS** | artifacts, lineage packages, Weathership memory, backup objects | Relational SoR |
| **Logical packages** | DataFusion (`signals-df`) | portable Parquet backup/verify | Live multi-writer SoR |

## Atlas → Kudu (via pglite FDW)

| Artifact | Path |
|----------|------|
| DDL (Kudu) | `config/atlas/kudu_projections.sql` |
| FDW (on pglite) | `config/atlas/kudu_projections_fdw.sql` |
| Seed | `just atlas-kudu-projections-seed` |
| Outbox contract | [Atlas → Kudu outbox](./atlas-kudu-outbox.md) |

Atlas **continues to use AGE on Postgres** as SoR. Projections are **derived**;
consumers on pglite query foreign tables. Continuous fill needs the **outbox
worker** (notifications → Impala UPSERT).

**Still required for “fully leverage”:**

1. Outbox worker (per-key order, at-least-once)  
2. True `kudu_scan` / libkudu_client for pk_lookup latency  
3. Atlas/AGE and app SQL prefer foreign tables for bulk entity/tag joins  

## Ranger → Kudu (via pglite FDW)

| Artifact | Path |
|----------|------|
| DDL (Kudu) | `config/ranger/kudu_projections.sql` |
| FDW (on pglite) | `config/ranger/kudu_projections_fdw.sql` |
| Seed | `just ranger-kudu-projections-seed` |

Ranger **admin** remains on Postgres. Tag/resource denorm lives on Kudu and is
**read through FDW** so multi-engine load does not thrash `x_tag*` heaps.
TagSync / outbox → UPSERT is near-term wiring.

## RustFS (object store)

| Item | Value |
|------|--------|
| Data dir | `$SIGNALS_DATA_ROOT/rustfs` (default `/raid/signals/rustfs`) |
| S3 API | `http://127.0.0.1:9010` path-style |
| Console | `http://127.0.0.1:9011` |
| Lab creds | `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` (secretspec in shared envs) |
| Client | `mc` → alias `local` |
| Buckets | `signals-artifacts`, `signals-lineage`, `weathership-memory`, `signals-backup` |
| Process | `processes.rustfs` (default stack) |

## Implications for signals-protocol

Discovery should advertise Atlas, Ranger, OL, **OBJECT_STORE**, and that
governance bulk SQL is available via **pglite + FDW** (not “raw Kudu only”).

Engines leave SoR writes to Atlas/Ranger APIs; bulk analytics and tag joins go
through the scale plane above.

## Ops checklist

```bash
just bootstrap
devenv up -d
just atlas-kudu-projections-seed   # Kudu tables + foreign tables on pglite
just ranger-kudu-projections-seed
just gov-kudu-projections-seed     # both
mc ls local/
```

## Related

- [Atlas → Kudu outbox](./atlas-kudu-outbox.md)
- [Storage and backup](../operations/storage-and-backup.md)
- [Signals protocol core](./signals-protocol-core.md)
- [OpenLineage + Atlas](./openlineage-atlas.md)
