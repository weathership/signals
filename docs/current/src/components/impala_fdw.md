# Impala FDW

PostgreSQL foreign data wrapper for the Impala + Kudu data plane, maintained as
`components/impala_fdw` → [weathership/impala_fdw](https://github.com/weathership/impala_fdw).

**Full specification:** [`components/impala_fdw/docs/SPEC.md`](https://github.com/weathership/impala_fdw/blob/trunk/docs/SPEC.md)
(in-tree: `components/impala_fdw/docs/SPEC.md` after submodule init).

## Scope

| | |
|--|--|
| Hot storage | Kudu (`STORED AS KUDU`); `kudu_scan` via `libkudu_client` |
| Warm storage | Iceberg and Impala `UNION ALL` views via `impala_sql` (HS2) |
| Identity | Kerberos: Postgres GSSAPI role is the Impala/Kudu principal |
| Access control | Postgres GRANT + RLS / security-barrier views |

Applications and governance tooling reach the data plane through
**PostgreSQL + impala_fdw**. Impala remains the SQL engine; HS2 is the
transport behind the FDW.

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