# Nix store search: Thrift 0.22 and kudu GSSAPI shims

Searched `/nix/store` (dir names + `find` for the ELF/headers).

## What is in Nix vs toolchain

| Artifact | Nix store | Impala toolchain |
|----------|-----------|------------------|
| libthrift | **only** `thrift-0.22.0` (`libthrift.so.0.22.0`) | `thrift-0.16.0-p7` (`libthrift-0.16.0.so`) |
| libgssapi_krb5.so.2 | `krb5-1.22.1-lib` (and older 1.21.3 leftovers) | not shipped next to kudu client |
| libsasl2 | `cyrus-sasl-2.1.28` soname **.so.3** | kudu NEEDED **.so.2** (already shimmed) |
| TProtocol.h | 0.22 has `writeUUID_virt` before read slots | 0.16 does not |

## FDW link pin

- `impala-fdw:build` fails if `ldd` does not show `libthrift.so.0.22` or if it shows `libthrift-0.16`.
- Makefile uses `-Wl,--disable-new-dtags` so the extension has **DT_RPATH** (searched for `libkudu_client` NEEDED) rather than RUNPATH.
- `.devenv/impala/lib` now also shims `libgssapi_krb5.so.2`, `libkrb5.so.3`, `libssl.so.3`, `libcrypto.so.3`.

Verified `ldd` (no `LD_LIBRARY_PATH`): `libgssapi_krb5.so.2` resolves; no Thrift 0.16.

FDW `SELECT` UNION + `INSERT` tier0 still green after the relink.
