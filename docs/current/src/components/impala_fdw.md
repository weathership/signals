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

## Role

```
PostgreSQL (:5455)  --impala_fdw-->  Impala HS2 (:21050)  -->  Kudu (:7051)
                         \------ kudu_scan (gov shapes) ------/
```

Postgres remains the primary front end for AGE / Atlas / Ranger **metadata**
SQL. The FDW supplies **row and sample data** from Kudu, with Impala as the
default SQL adapter and Kudu scans for the known Atlas+Ranger+sigint algebra
(see SPEC §6).

## Build

```bash
git submodule update --init components/impala_fdw
just impala-fdw-build
```

## Status

Phase 0 scaffold: extension registers and validates options; scans raise until
HS2/Kudu executors land (SPEC §14).
