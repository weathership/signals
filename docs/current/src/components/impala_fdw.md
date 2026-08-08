# Impala FDW

PostgreSQL foreign data wrapper for the Impala + Kudu data plane, maintained as
`components/impala_fdw` → [weathership/impala_fdw](https://github.com/weathership/impala_fdw).

**Full specification:** [`components/impala_fdw/docs/SPEC.md`](https://github.com/weathership/impala_fdw/blob/trunk/docs/SPEC.md)
(in-tree: `components/impala_fdw/docs/SPEC.md` after submodule init).

## Scope

| | |
|--|--|
| Storage | **Kudu only** (via Impala tables `STORED AS KUDU`) |
| Default path | Impala HS2 (C/C++ thrift client) — SQL-shaped queries |
| Fast path | Direct **C++ `libkudu_client`** for closed governance ops |
| Identity | **End-to-end Kerberos**: Postgres GSSAPI role ↔ same principal on Impala/Kudu |
| Access control | Postgres GRANT + **RLS** / security-barrier views; **not multi-tenant** FDW |
| Non-goals | Iceberg, HMS, Java-in-process clients, FDW multi-tenancy, DML in v0 |

## Access default: FDW-only / no-JDBC

**Product direction:** applications and governance tooling talk to the data plane
through **PostgreSQL + impala_fdw**, not through a first-class **JDBC/HS2 client
surface** for every consumer.

| Path | Role |
|------|------|
| **Postgres (:5455) + FDW** | **Default** app / agent / AGE-adjacent access |
| Impala HS2 | Transport **behind** the FDW (and minicluster ops), not the primary API we optimize for |
| Direct JDBC to Impala | Supported only as interim / debug — not the long-term product contract |

That lets the stack slim further after Kudu-only / no-HDFS:

- Fewer things need a full JDBC stack, HiveServer2 client libraries in app code, or
  dual auth stories (Postgres vs Impala-as-primary).
- Identity stays **one principal story** (Kerberos into Postgres; FDW carries it to
  Impala/Kudu per SPEC).
- Impala remains the SQL/execution engine; **exposure** is FDW-shaped.

Same debt class as Hadoop-at-build and Ranger Nashorn: today’s HS2/JDBC tooling may
still exist for bootstrap and FE tests; the **default we design toward** is
FDW-only / no-JDBC for product consumers.

## Role

```
PostgreSQL (:5455)  --impala_fdw-->  Impala HS2 (:21050)  -->  Kudu (:7051)
                         \------ kudu_scan (gov shapes) ------/
```

Postgres is the primary front end for AGE / Atlas / Ranger **metadata** SQL and,
going forward, for **row/sample data** via the FDW. Impala is the SQL adapter
behind the FDW; Kudu scans cover the known Atlas+Ranger+sigint algebra (SPEC §6).

## Build

```bash
git submodule update --init components/impala_fdw
just impala-fdw-build
```

## Status

**Phase 1a:** HS2 foreign scans with **column projection**, **eq/range predicates**,
**IN / = ANY pushdown**, and EXPLAIN `ShapeId` / remote SQL. Atlas typed Kudu
projections: `config/atlas/kudu_projections.sql` + `kudu_projections_fdw.sql`.
Outbox: [Atlas → Kudu outbox](../architecture/atlas-kudu-outbox.md).

**Phase 3 (lab-ready):** direct **`kudu_scan`** via `libkudu_client`
([`kudu_scan.md`](https://github.com/weathership/impala_fdw/blob/trunk/docs/kudu_scan.md)).
PR-K0–K4 + checkpoint-02 (LIMIT under agg/sort, multiset gates, warm-cache
~0.5 ms, `hs2-smoke` link). Atlas FTs default `access=auto`. **PR-K5**
Kerberos plan verified (staged K5a–K5e in `kudu_scan.md`); not yet implemented.

```bash
just impala-fdw-build && just impala-fdw-install
just atlas-kudu-projections-seed
just atlas-frontier-bench
```