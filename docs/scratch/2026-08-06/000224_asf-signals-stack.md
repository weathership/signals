# asf-signals stack

**Name:** **asf-signals** — the ASF-licensed (and ASF-adjacent) data-platform
slice of signals-360 that other hosts (and later products) can reason about as
one unit.

## Scope

| Component | License posture | Role in stack |
|-----------|-----------------|---------------|
| **Atlas** | ASF | Metadata / governance graph (AGE backend in our fork) |
| **Ranger** | ASF | Tag-based authorization; TagSync from Atlas |
| **Kudu** | ASF | Storage (primary analytic store for signals tags path) |
| **Impala** | ASF | SQL / HS2; HMS-free catalog on signals Postgres |
| **impala_fdw** | ASF-licensed where Postgres FDW license does not take precedence | Postgres → Impala HS2 → **Kudu only** (signals dual-path design) |

Supporting host pieces that are *not* named “asf-signals” but required to run it:

- PostgreSQL + AGE, Kerberos (`DEV.VISTA.ZNDX.ORG`), product `config/`, SecretSpec
- Submodule branch line for forks: **`rch/devenv`** (consumable by non-signals hosts)

## Readiness checklist (host: signals devenv)

After **Impala `buildall`** (post-bootstrap) **and** Ranger admin install/setup:

| Piece | Built | Running (typical) |
|-------|-------|-------------------|
| Atlas webapp + process | ✓ | `:21010` |
| Kudu master/tserver | ✓ | `:7051` / `:7050` |
| Impala toolchain bootstrap | ✓ | — |
| Impala binaries (`impalad`, …) | after `impala:build` | HS2 `:21050` |
| Ranger jars (`.devenv/m2`) + admin tree | build/install tasks | Admin `:6080` |
| impala_fdw | **next** after stack green | extension on PG `:5455` |

**Naming intent:** call the five-component set **asf-signals**; do not fold
sigint classification Python or full k8s/zarf product packaging into that name.

## devenv orientation (not system installs)

| Concern | Location |
|---------|----------|
| Tooling (cmake, jdk11/17, gcc, …) | devenv `packages` / `languages.*` |
| Maven artifacts (Ranger, Atlas, Kudu client) | `$SIG_MAVEN_REPO` = `$PWD/.devenv/m2` |
| Ranger admin tree | `.devenv/ranger/admin` |
| Impala toolchain | `components/impala/toolchain/` (bootstrap task) |
| Hadoop client tarball | Under Impala toolchain only — **build link tax**, not a stack service |
| Kudu / Impala binaries | `components/*/build/…` (not `/usr/local`) |
| Runtime processes | `devenv up` / process-compose (no HDFS/YARN for Kudu-only) |

Do **not** require distro packages like `apt install openjdk-11-jdk` or
`mvn install` into `~/.m2` for asf-signals work.

## Isolation rules (learned)

- Do **not** put `pkgs.thrift` / `pkgs.boost` in host `packages` — they poison
  `CMAKE_INCLUDE_PATH` / PATH so Impala resolves Nix thrift 0.22 instead of
  toolchain thrift 0.16. FDW task pins them via `${pkgs.thrift}` only.
- `impala:build` filters thrift/boost from PATH and CMAKE_*_PATH; FindThriftCpp
  uses `NO_DEFAULT_PATH` when `THRIFT_CPP_HOME` is set.
- JDKs: `${pkgs.jdk11}` (Ranger **interim** — Nashorn; plan to ditch and modernize),
  `${pkgs.jdk17}` (Kudu Gradle), not store greps.

## Next

1. Finish `impala:build` (or `devenv shell -- ./scripts/impala-build-isolated.sh`)
2. `ranger:install` + `setup.sh` → start ranger-admin under `.devenv/`
3. `devenv up` / process health for full graph
4. **impala_fdw** build/install against HS2 + Kudu-only path
