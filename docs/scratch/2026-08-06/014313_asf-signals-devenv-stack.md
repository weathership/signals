# asf-signals stack under `devenv up -d`

## Working (2026-08-06)

| Process | Port | Health |
|---------|------|--------|
| postgres | 5455 | ready (Atlas AGE + Ranger DBs) |
| kdc | 8848 | ready |
| atlas | 21010 | ACTIVE (AGE → postgres `signals`) |
| ranger-admin | 6080 | HTTP 302 (Postgres `ranger`) |
| kudu-master | 7051 / 8051 | ready |
| kudu-tserver | 7050 / 8050 | ready |
| impala-statestore | 24000 / 25010 | ready |

## Not yet ready

| Process | Issue |
|---------|-------|
| impala-catalogd | segfault after JVM bootstrap under Nix glibc isolation |
| impala-impalad | blocked on catalogd |

### Catalogd/JVM notes

- BE links need Nix OpenSSL 3.4+ (toolchain `libcrypto.so.3` → host OpenSSL lacks `OPENSSL_3.4.0`).
- Use `ld-linux --library-path` **without** exporting `LD_LIBRARY_PATH` so child `/bin/sh` is not poisoned by Nix libc (`__tunable_is_initialized` / `GLIBC_PRIVATE`).
- Statestore (no JVM) is healthy with that pattern.
- Catalogd loads libjvm and segfaults immediately after “Picked up JAVA_TOOL_OPTIONS” (jamm agent + add-opens). Needs deeper JVM/native isolation (likely full Nix JAVA_HOME + matching glibc, or a pure host-JDK path).

## FE build

- `impala:build-fe` now builds `fe` + `impala-package` → `package-classpath.txt`.
- Ranger 3.0 splits `ranger-plugins-audit` into a pom aggregator; `ranger:build` installs a jar shim from `ranger-audit-core` for Impala FE.

## Ops

```bash
devenv up --detach   # or: devenv up -d
devenv processes list
curl -s http://127.0.0.1:21010/api/atlas/admin/status
curl -sI http://127.0.0.1:6080/ | head -1
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8051/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:25010/
```

Prereqs: `ranger:build` + `ranger:install` + `ranger:setup`, `atlas:build`, `kudu:build-cpp`, Impala BE build, `impala:build-fe`.

## Related

- Isolation constraint: `014357_devenv-isolation-constraint.md`
