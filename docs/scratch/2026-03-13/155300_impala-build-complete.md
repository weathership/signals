# Impala Full Build Complete — Nix/Toolchain ABI Resolution

## Summary

Successfully completed `buildall.sh -notests -noclean` producing all Impala binaries
(impalad, statestored, catalogd, admissiond). This required resolving a systematic
ABI incompatibility between the Nix devenv (glibc 2.42, GCC 15, OpenSSL 3.6.1) and
the Impala toolchain (GCC 10.4.0, targeting system glibc 2.35, OpenSSL 3.0.2).

## Root Problem

The Nix devenv injects its libraries into `CMAKE_LIBRARY_PATH`, `CMAKE_INCLUDE_PATH`,
and `PKG_CONFIG_PATH`. CMake's `find_library()` and `find_path()` search these before
system paths. When Nix's libraries get linked into toolchain binaries, they embed
Nix RPATH and reference glibc 2.38+ symbols unavailable on the host system.

## Fixes Applied

### 1. System Library Symlinks in Toolchain GCC lib64

**Path:** `toolchain/toolchain-packages-gcc10.4.0/gcc-10.4.0/lib64/`

System glibc 2.34+ merged librt/libdl/libpthread into libc, so unversioned `.so`
linker symlinks don't exist on the system. Nix provides them (pointing to Nix glibc).
CMake finds Nix's versions and injects Nix RPATH into all binaries.

Created symlinks to system stubs:
```
librt.so      -> /lib/x86_64-linux-gnu/librt.so.1
libdl.so      -> /lib/x86_64-linux-gnu/libdl.so.2
libpthread.so -> /lib/x86_64-linux-gnu/libpthread.so.0
```

Kerberos libraries (system has .so.N but no unversioned .so):
```
libgssapi_krb5.so  -> /lib/x86_64-linux-gnu/libgssapi_krb5.so.2
libkrb5.so         -> /lib/x86_64-linux-gnu/libkrb5.so.3
libk5crypto.so     -> /lib/x86_64-linux-gnu/libk5crypto.so.3
libkrb5support.so  -> /lib/x86_64-linux-gnu/libkrb5support.so.0
libcom_err.so      -> /lib/x86_64-linux-gnu/libcom_err.so.2
```

OpenSSL (both versioned and unversioned):
```
libssl.so       -> /lib/x86_64-linux-gnu/libssl.so
libssl.so.3     -> /lib/x86_64-linux-gnu/libssl.so.3
libcrypto.so    -> /lib/x86_64-linux-gnu/libcrypto.so
libcrypto.so.3  -> /lib/x86_64-linux-gnu/libcrypto.so.3
```

### 2. CMAKE_LIBRARY_PATH Ordering (impala-config-local.sh)

Put GCC lib64 FIRST in CMAKE_LIBRARY_PATH so CMake finds system symlinks before Nix:
```bash
_GCC_LIB64="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/lib64"
export CMAKE_LIBRARY_PATH="${_GCC_LIB64}${CMAKE_LIBRARY_PATH:+:$CMAKE_LIBRARY_PATH}"
```

### 3. OpenSSL pkg-config and Include Filtering

CMake's FindOpenSSL uses pkg-config (returns Nix's OpenSSL 3.6.1) and
CMAKE_INCLUDE_PATH (has Nix's openssl-3.6.1-dev/include). Both must be filtered:
```bash
for _var in PKG_CONFIG_PATH CMAKE_INCLUDE_PATH; do
  export "$_var"=$(echo "${!_var}" | tr ':' '\n' | grep -v 'openssl' | paste -sd':')
done
```

**Why both matter:**
- Without PKG_CONFIG_PATH filtering: FindOpenSSL HINTS point to Nix libcrypto.so
  (GLIBC_2.38 undefined references)
- Without CMAKE_INCLUDE_PATH filtering: Headers from OpenSSL 3.6.1 define
  `EVP_MD_CTX_size` as `EVP_MD_CTX_get_size_ex` (introduced in 3.5.0), which
  doesn't exist in system libcrypto.so (3.0.2)
- With both filtered: CMake finds system OpenSSL 3.0.2 headers (/usr/include/openssl/)
  and libraries (via GCC lib64 symlinks) — consistent ABI

### 4. System Linker in Toolchain GCC

**Path:** `toolchain/.../gcc-10.4.0/x86_64-pc-linux-gnu/bin/`

GCC searches this cross-tools directory before PATH for binutils. Created:
```
ld -> /usr/bin/ld
as -> /usr/bin/as
```
Prevents Nix's gcc-wrapper `ld` (which adds Nix RPATH) from being used.

### 5. Kudu C++ Client Version Switch

The locally-built Kudu 1.19.0-SNAPSHOT was compiled with Nix GCC 15/glibc 2.42.
Its `libkudu_client.so` references GLIBC_2.36+ and GLIBCXX_3.4.29+ symbols.

Switched to the pre-built toolchain Kudu 879a8f9e2:
- `impala-config-branch.sh`: Commented out `IMPALA_KUDU_VERSION=1.19.0-SNAPSHOT`
- `impala-config-local.sh`: Commented out `KUDU_BUILD_DIR` and `KUDU_CLIENT_DIR`
- Commented out Maven repo override (toolchain repo has matching 879a8f9e2 jars)

### 6. SignalsDdlExecutor Import Fix

`EventSequence` moved from `org.apache.impala.catalog.events` to `org.apache.impala.util`.

## Key Files

| File | Purpose |
|------|---------|
| `bin/impala-config-local.sh` | Nix compatibility settings (CMAKE_LIBRARY_PATH, PKG_CONFIG_PATH, CMAKE_INCLUDE_PATH filtering) |
| `bin/impala-config-branch.sh` | Kudu version override (commented out) |
| `toolchain/.../gcc-10.4.0/lib64/` | System library symlinks |
| `toolchain/.../gcc-10.4.0/x86_64-pc-linux-gnu/bin/` | System linker symlinks |
| `fe/.../service/SignalsDdlExecutor.java` | Fixed EventSequence import |

## Build Command

```bash
source bin/impala-config.sh && ./buildall.sh -notests -noclean
```

Build type: DEBUG (default). Produces ~500MB impalad binary at
`be/build/debug/service/impalad`.

## Critical Rules

1. **Never run bare `cmake .`** — always use `buildall.sh` which passes
   `-DCMAKE_TOOLCHAIN_FILE=cmake_modules/toolchain.cmake` to set toolchain GCC
2. **Never set OPENSSL_ROOT_DIR** — it adds NO_DEFAULT_PATH which prevents
   CMAKE_LIBRARY_PATH from being searched. Filter pkg-config/includes instead.
3. **buildall.sh always deletes CMakeCache.txt** (line 535) — no way to pre-populate
   CMake cache variables
