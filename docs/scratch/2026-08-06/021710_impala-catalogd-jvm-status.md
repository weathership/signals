# Impala catalogd JVM — status (devenv-only)

## Working
- Statestore under `ld-linux --library-path` (no JVM)
- Atlas / Ranger / Kudu / Postgres / KDC under process-compose

## Catalogd remaining failure
Segfault immediately after JVM bootstrap (`Picked up JAVA_TOOL_OPTIONS` then minidump).
Not jamm-specific (`--java_weigher=sizeof` still dies).

## Isolation groundwork landed in devenv.nix
1. **jdk21_headless** for Impala processes (fewer native NEEDED than full GUI jdk)
2. **No host multiarch** on library path
3. **`.devenv/impala/lib`**: `libsasl2.so.2` → Nix so.3; kudu *client only* (not whole kudu/lib — ships conflicting libstdc++)
4. **Nix libstdc++** (`stdenv.cc.cc.lib`) for BE+JVM
5. **`LD_PRELOAD=libjsig`** for signal chaining (Impala installs handlers before JNI)
6. **`ld-linux --library-path`** without exporting `LD_LIBRARY_PATH` (protects child `/bin/sh`)
7. Pin `JAVA_HOME` before `impala-config.sh`

## Likely next angles
- catalogd ELF **RUNPATH** still points at full GUI openjdk used at link time — may need `patchelf --set-rpath` under `.devenv` or rebuild BE against headless JDK
- CreateJavaVM under mixed BE (gcc-10) + JDK (gcc-15 libstdc++) still suspect
- `bwrap --ro-bind nix-bash /bin/sh` for `GetJavaMajorVersion` shell-out if sh pollution returns
- Optional Domen/devenv: first-class “native binary + embedded JVM” process helper (library-path + jsig + headless jdk)

## Do not
- Fall back to system JDK or `/lib/x86_64-linux-gnu` as the fix
