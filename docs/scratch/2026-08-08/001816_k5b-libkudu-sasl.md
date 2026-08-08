# K5b — libkudu SASL + principal-keyed client cache

**Date:** 2026-08-08  
**Status:** Landed (client code + nosasl regression). Live `SIGNALS_KUDU_KERBEROS=1` success is K5c smoke.

## What shipped

### `ImpalaKuduAuth` (exec_kudu.h)
- `mode` (`nosasl` | `kerberos`), `principal`, `ccache`, `keytab`, `sasl_protocol` (NULL → `"kudu"`)
- `impala_kudu_scan_open(..., const ImpalaKuduAuth *auth, char **err)`

### Client builder (`exec_kudu.cpp`)
When `auth` is kerberos (anything other than nosasl/NULL):
1. Optional **keytab → ccache kinit** via libkrb5 (`krb5_get_init_creds_keytab` + `krb5_cc_store_cred`)
2. Temporarily set `KRB5CCNAME` for `Build` (RAII restore)
3. `builder.sasl_protocol_name(proto)` + `require_authentication(true)`

### Cache key (KD5)
```
canon_masters|mode|principal|ccache|keytab
```
Prevents cross-principal client reuse inside one backend. Ambient `KRB5CCNAME` folds into key when kerberos and no explicit ccache.

### Begin wiring (`impala_fdw.c`)
- USER MAPPING: `principal`, `keytab`, `ccache`
- Env fallback: `SIGNALS_KRB_USER_KEYTAB`
- Principal still from `impala_fdw_resolve_principal`
- DEBUG1 logs auth + principal on kudu_scan open

### Build
- Makefile links `-lkrb5` when `IMPALA_FDW_WITH_KUDU=1`
- `impala-fdw:build` exports `SIG_KRB5_INC` / `SIG_KRB5_LIB`

## Smoke (nosasl lab, MODE=0)

```
EXPLAIN … LIMIT 5  → AccessMethod: kudu_scan  ✓
SELECT type_name, name FROM atlas_entity_flat LIMIT 5  → hive_table | fdw_smoke  ✓
ALTER FT access=kudu_scan; WHERE type_name = 'hive_table'  → kudu_scan + 1 row  ✓
ldd impala_fdw.so → libkudu_client + libkrb5  ✓
```

## Not in K5b
- Live cluster with `rpc_authentication=required` (K5a MODE=1 + K5c)
- EXPLAIN principal attribute / log_path_choice auth (K5c)
- HS2 SASL (K5d)

## Files
- `components/impala_fdw/src/exec_kudu.{h,cpp}`
- `components/impala_fdw/src/impala_fdw.c`
- `components/impala_fdw/Makefile`
- `components/impala_fdw/docs/kudu_scan.md` (0.2.9)
- `devenv.nix` (impala-fdw:build krb5)
