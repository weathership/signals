# Constraint: stay inside devenv isolation

When wiring or debugging asf-signals (Impala, Atlas, Ranger, Kudu, Maven, JDK):

## Prefer

- `devenv` / Nix packages (`pkgs.*` in `devenv.nix`)
- Project-local state under `.devenv/` (m2, ranger admin, atlas data, logs)
- `SIG_MAVEN_REPO` / `.devenv/m2` — not `~/.m2`
- Toolchain under `components/*/toolchain` only when the ASF build requires it, still driven from devenv tasks
- Process-compose env assembled in `devenv.nix` (explicit paths, no ambient host pollution)

## Treat as bugs to fix (not workarounds)

Any behavior that reaches **outside** devenv for runtime or build deps:

| Smell | Example | Desired |
|-------|---------|---------|
| Host multiarch libs | `/lib/x86_64-linux-gnu/libsasl2.so.2` on `LD_LIBRARY_PATH` / library-path | Provide soname via Nix/cyrus_sasl or rebuild BE against Nix SASL |
| System JDK | `/usr/lib/jvm`, Ubuntu OpenJDK on `PATH` ahead of devenv | Pin `JAVA_HOME` to `pkgs.jdk` / `pkgs.jdk11` only |
| Global Maven | `~/.m2`, user settings.xml | `SIG_MAVEN_REPO=.devenv/m2` + `MAVEN_ARGS=-Dmaven.repo.local=...` |
| System OpenSSL/crypto | toolchain `libcrypto` → host OpenSSL | `SIG_SSL_*` + Nix openssl first (already) |
| Ambient `LD_LIBRARY_PATH` from shell/direnv | pollutes child `/bin/sh` | Impala: `ld-linux --library-path` without exporting LD_LIBRARY_PATH |
| Hardcoded `/usr`, `/usr/local` in component configs | install.properties, cmake find modules | devenv-relative or Nix store paths |

## Catalogd JVM follow-up (apply this constraint)

Do **not** “fix” the catalogd segfault by switching to a host JDK or more `/lib/x86_64-linux-gnu` entries. Instead:

1. Force catalogd/impalad `JAVA_HOME` to the same Nix OpenJDK as devenv (`pkgs.jdk` / profile).
2. Put that JDK’s `lib/server` + deps on `--library-path` from Nix store only.
3. Satisfy `libsasl2.so.2` without host multiarch if possible (Nix package, compat symlink in `.devenv`, or BE relink to so.3).
4. Keep `SIG_MAVEN_REPO` for any FE/classpath jar resolution.

## Check when debugging

```bash
# Should not be required for a healthy stack:
ldd <binary> | grep -E '/usr/|/lib/x86_64'
echo "JAVA_HOME=$JAVA_HOME"   # expect /nix/store/...
echo "SIG_MAVEN_REPO=$SIG_MAVEN_REPO"  # expect $PWD/.devenv/m2
```
