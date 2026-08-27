# Kudu 1D ARRAY confirmed; FDW all types; HS2 CREATE unblocked to Kudu SASL

Guru: `#SL.00000026.KUDUARRAY`

## Kudu 1D ARRAY — confirmed on this 1.19.0-SNAPSHOT

This tree already exposes 1D arrays as `DataType::NESTED` + `KuduArrayTypeDescriptor` (C++) / `ColumnSchemaBuilder#array(true)` (Java). Runtime probe:

- `scripts/kudu_array_probe.cc` — INT32 PK + `NESTED INT64[]`, insert `{1,2,3}`, scan round-trip, drop.
- Output: `KUDU_1D_ARRAY_OK rows=1 version=1.19.0-SNAPSHOT element=INT64`
- `scripts/kudu_types_probe.cc` left `impala::signals_dataproducts.kudu_types_probe` with every scalar plus `INT64[]`.

Limits (Kudu, not us): 1D only; no nested-of-nested; no DECIMAL128 arrays (precision > 18); SERIAL is UINT64 and is not a 1D array element.

Impala already maps `ARRAY<item>` → `ColumnSchemaBuilder#array()` (`KuduCatalogOpExecutor.createColumnSchema`).

## impala_fdw — all Kudu scalars + 1D ARRAY

`kudu_scan` no longer stops at the Atlas type allowlist.

| Kudu | Postgres (FT) | Notes |
|------|----------------|-------|
| BOOL | boolean | |
| INT8/16/32/64 | smallint/int/bigint | INT predicates work (`gpu_index = 0`) |
| FLOAT/DOUBLE | real/double precision | |
| STRING/VARCHAR | text/varchar | |
| BINARY | bytea | `\x` hex |
| UNIXTIME_MICROS | timestamptz | µs since 1970 |
| DATE | date | days since 1970 |
| DECIMAL | numeric | unscaled + scale |
| SERIAL | bigint | UINT64 via `cell()` |
| NESTED 1D ARRAY | `bigint[]` etc. | empty validity bitmap = all valid |

Verified on devenv PG `:5455`:

```
 id | c_bool | c_i8 | c_i16 | c_i32 | c_i64 | c_f | c_d | c_str | c_bin | c_ts | c_date | c_dec | c_vc | c_arr
  1 | t | -8 | -16 | 32 | 64 | 1.5 | 2.5 | hello | dead | 2025-08-23 23:00:00+00 | 2026-08-24 | 12.34 | varchar | {1,2,3}
```

`gpu_metrics` still 24954 rows; `WHERE gpu_index = 0` pushes INT32.

Install: copy `components/impala_fdw/impala_fdw.so` → `.devenv/pg-ext/lib/` (do **not** run `impala-fdw:install` — it `DROP EXTENSION CASCADE`s the gpu_metrics FTs). SQL: `config/platform/kudu-types-fdw.sql`.

DECIMAL predicates and ARRAY predicates fail-fast (not implemented / Kudu does not predicate arrays).

## HS2 CREATE TABLE STORED AS KUDU

Three layers were actually blocking CREATE, not a missing DDL path:

1. **HMS probe** — `KuduTable.isHMSIntegrationEnabled` now returns false under `-Dsignals.hms_free_mode=true` (already in FE jar).
2. **Empty storage-handler map** — HMS-free `SignalsDdlExecutor.createTable` now seeds `storage_handler`, `kudu.master_addresses`, `kudu.table_name`. Without this, `isSynchronizedTable` threw `IllegalStateException: null` in 2ms.
3. **Local catalog duplicate names** — `MultiMetaProvider.loadTableList` used to throw `Ambiguous table name: gpu_metrics_tier0` (Kudu registry ∪ Iceberg). Fail-open: keep first, log warn.

After those, CREATE reaches Java `KuduClient.createTable('impala::signals_dataproducts.hs2_kudu_create_probe')` (~450ms) and fails SASL:

```
ConnectToCluster: Unable to connect to master 127.0.0.1:7051
Server requires Kerberos, but this client is not authenticated (missing or expired TGT)
```

KUDU-2121 `Negotiator.createSaslClient` is now inside `Subject.callAs` (JDK 17 `kudu-client` jar copied over `.devenv/m2/.../kudu-client-879a8f9e2.jar`). Standalone JDK 21 JAAS login from `/tmp/krb5cc_impala` is `LOGIN_OK`. Catalogd JAAS debug also prints `Commit Succeeded` against `/tmp/krb5cc_impala_internal`.

The remaining miss is **which address the Java client SASL's**: master bind is `127.0.0.1:7051`, advertised is `tinybox.dev.vista.zndx.org:7051`. Java still tries `127.0.0.1`, so GSSAPI asks for `kudu/127.0.0.1` (not in the KDC). Do **not** restart kudu-master during the gpu_metrics soak to flip bind; next devenv cycle should bind/advertise the FQDN only.

Ticket-cache property (if restarting catalogd): `-Dkudu.krb5ccname=/tmp/krb5cc_impala` (not `kudu.ticket-cache`). kinit:

```
KRB5CCNAME=/tmp/krb5cc_impala kinit -kt .devenv/kdc/impala.keytab \
  impala/tinybox.dev.vista.zndx.org@DEV.VISTA.ZNDX.ORG
```

Patched into the live FE jar (javac --release 11 + `jar uf`): `SignalsDdlExecutor`, `MultiMetaProvider`. Rebuild with `impala:build-fe` when devenv tasks are healthy.

## Files

- `components/impala_fdw/src/exec_kudu.cpp`, `src/kudu_pred.c`
- `components/impala/fe/.../SignalsDdlExecutor.java`, `MultiMetaProvider.java`, `KuduTable.java`
- `components/kudu/java/kudu-client/.../Negotiator.java`
- `scripts/kudu_array_probe.cc`, `scripts/kudu_types_probe.cc`
- `config/platform/kudu-types-fdw.sql`
