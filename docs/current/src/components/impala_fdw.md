# Impala FDW

PostgreSQL foreign data wrapper for Apache Impala (HS2), maintained as
`components/impala_fdw` → [weathership/impala_fdw](https://github.com/weathership/impala_fdw).

## Scope

**Kudu storage only.** Impala is the HS2 frontend; foreign tables map to Impala
tables backed by Kudu. Iceberg and other Impala formats are out of scope for v1.

## Role

Lets governance / AGE SQL on Postgres join live **Kudu** data without bulk copy:

```
PostgreSQL (:5455)  --impala_fdw-->  Impala HS2 (:21050)  -->  Kudu (:7051)
```

Complementary to Atlas (metadata catalog) and the HMS-free catalog registry.

## Build

```bash
git submodule update --init components/impala_fdw
just impala-fdw-build
# or: devenv tasks run impala-fdw:build
```

Install into the Postgres prefix (`make install`), then:

```sql
CREATE EXTENSION impala_fdw;
```

## Status

Scaffold: extension registers, options validate, scans raise until HS2 client
is wired. Defaults match signals devenv (`host=127.0.0.1`, `port=21050`).
