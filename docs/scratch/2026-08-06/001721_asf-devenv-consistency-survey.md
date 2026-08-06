# asf-signals devenv consistency survey

Date: 2026-08-06

## Principle

ASF components (Atlas, Ranger, Kudu, Impala, impala_fdw) build and install
**inside the signals devenv / project tree**, not via system packages or `~/.m2`.

| Concern | Correct location | Anti-pattern |
|---------|------------------|--------------|
| JDKs | `pkgs.jdk11` / `pkgs.jdk17` / languages.java | `/usr/lib/jvm`, apt openjdk |
| Maven SNAPSHOTs | `$SIG_MAVEN_REPO` = `$PWD/.devenv/m2` | `~/.m2/repository` |
| Ranger admin | `.devenv/ranger/admin` | CDP tarball under Impala toolchain, `/usr` |
| Impala toolchain | `components/impala/toolchain/` | system gcc/thrift/boost |
| Kudu binaries | `components/kudu/build/latest` | `/usr/local` |
| Atlas/Ranger jars | `.devenv/m2` via devenv tasks | system Maven install |

## Findings (this pass)

### Fixed

1. **`ranger:build` / `kudu:build-cpp`** — use `${pkgs.jdk11}` / `${pkgs.jdk17}` instead of scanning `/nix/store/*openjdk*`.
2. **`SIG_MAVEN_REPO` before `cd`** — Atlas/Ranger/Kudu/Impala tasks no longer default to `components/*/.devenv/m2` when `SIG_MAVEN_REPO` is unset.
3. **`ranger:db-setup`** — removed `~/.m2` fallback for PostgreSQL JDBC (project m2 or download into `.devenv/ranger/lib`).
4. **`ranger:install`** — prefer `ranger-*-admin.tar.gz` from local build; remove leftover CDP-named trees under `.devenv/ranger/`.
5. **`impala-config-local.sh`** — set `SIG_MAVEN_REPO` + `MAVEN_ARGS=-Dmaven.repo.local=…` so FE builds outside `devenv tasks` still isolate Maven.
6. **Global `pkgs.thrift` / `pkgs.boost` removed** — they poisoned `CMAKE_INCLUDE_PATH` / `PKG_CONFIG_PATH` so Impala BE resolved **Nix thrift 0.22** for includes/libs while the toolchain is thrift **0.16**. `impala_fdw:build` still pins `${pkgs.thrift}` / `${pkgs.boost.dev}` explicitly.
7. **`impala:build` isolation** — unset `CMAKE_INCLUDE_PATH` / `CMAKE_LIBRARY_PATH` / `CMAKE_PREFIX_PATH`; strip thrift/boost from `PKG_CONFIG_PATH`; drop CMakeCache if it references Nix thrift/boost.
8. **Impala source** — add `#include <boost/scoped_array.hpp>` in `TSaslTransport.h` (missing header; fails cleanly once thrift/boost pollution is fixed).

### Remaining / watch

| Item | Status |
|------|--------|
| Impala submodule | Fix pushed to **`rch/signals`** and **`rch/devenv`** |
| Nested Kudu `devenv.nix` | Still installdir `usr/local` *under* build tree — OK for Kudu layout |
| Upstream bootstrap scripts in submodules | Still document apt/`~/.m2` — ignore; use host tasks |
| Impala `impala_python3` target | Can fail under devenv if venv pip SSL glitches; C++ may still complete |
| Ranger admin running `:6080` | After `ranger:install` + `setup.sh` |
| impala_fdw | After Impala binaries + HS2 up |

### Build state (updated)

1. **First attempt:** failed ~64% — Nix thrift 0.22 in CMakeCache + missing `boost/scoped_array.hpp`.
2. **After isolation:** thrift correctly toolchain **0.16.0**; cyrus_sasl from devenv; C++ compiling past 60%+.
3. **Python side:** `impala_python3` custom target hit pip SSL during reinstall; venv python itself imports OpenSSL 3.0.2 — may need re-run of that target only after C++ finishes.

## Task map (host `devenv.nix`)

```
ranger:build → .devenv/m2 (jdk11)
ranger:install → .devenv/ranger/admin
atlas:build → .devenv/m2
kudu:build-cpp → components/kudu/build/latest
kudu:install-java → .devenv/m2 (jdk17)
impala:bootstrap / impala:build → toolchain + .devenv/m2 Ranger plugins
impala-fdw:build → pkgs.thrift + pkgs.boost.dev (task-local only)
```
