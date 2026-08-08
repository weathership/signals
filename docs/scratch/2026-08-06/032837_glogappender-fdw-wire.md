# GlogAppender (post-JNI) + impala_fdw wire-up

## GlogAppender / natives
Impala already switches log4j to GlogAppender **after** JNI init:

1. Bootstrap: `config/impala/hadoop-conf/log4j.properties` → ConsoleAppender only
   (avoids libhdfs SEGV before natives exist).
2. `InitJvmLoggingSupport()` → `RegisterNatives(NativeLogger.Log, ...)`.
3. `JniCatalog` ctor → `GlogAppender.Install(...)` reconfigures root logger → glog.

Live proof (catalogd INFO):
```
GlogAppender.java:140] Logging (re)initialized. Impala: INFO, All other: INFO
```

Hardening landed:
- `IMPALA_JAVA_LIBRARY_PATH` = `be/build/latest/{util,service}` + hadoop native
  (NativeLibUtil fallback for `libloggingsupport.so`).
- Documented two-phase logging in `hadoop-conf/log4j.properties`.

## impala_fdw
Tasks:
- `impala-fdw:build` — PG16 synthetic `pg_config` + thrift/boost, produces `impala_fdw.so`
- `impala-fdw:install` — copy to `.devenv/pg-ext/`, register FDW + server `impala_kudu_srv`
- `impala-fdw:smoke` — HS2 `SELECT 1` + catalog objects

Also: Impala-style backtick quoting in FDW SQL generation (not PG double-quotes).

Verified:
```
hs2_smoke → ok columns=1 value0=1
pg: impala_fdw, impala_kudu_srv, foreign table fdw_smoke
```

### Open: HMS-free Kudu access type
```
AnalysisException: Operations not supported. Table default.fdw_smoke access type is: NONE
```
CREATE TABLE STORED AS KUDU succeeds; SELECT/INSERT blocked. FDW SQL path is correct
(`SELECT \`id\`, \`name\` FROM \`default\`.\`fdw_smoke\``). Next: set
`ACCESSTYPE_READWRITE` on HMS-free Kudu create in Impala catalog path.

## Commands
```bash
just impala-fdw-build
just impala-fdw-install
just impala-fdw-smoke
```
