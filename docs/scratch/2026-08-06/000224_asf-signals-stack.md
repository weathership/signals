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

## Next

1. `devenv tasks run impala:build` (long)
2. `ranger:install` + `setup.sh` → start ranger-admin
3. `devenv up` / process health for full graph
4. **impala_fdw** build/install against HS2 + Kudu-only path
