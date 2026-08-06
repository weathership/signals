# Ranger

Apache Ranger provides authorization and access control across the data platform.
In Signals 360, Ranger consumes **Atlas classifications** (SIGDG tags) and enforces
tag-based policies at query time in Impala.

## Role in the Stack

1. **Policy admin** — define allow/deny/mask rules on resources and tags.
2. **TagSync** — pull classifications from Atlas (`http://localhost:21010`) into Ranger’s tag store.
3. **Impala plugin** — enforce policies when users query Kudu/Iceberg tables via Impala.

See [Metadata Tagging](../architecture/meta-tagging.md) for the Atlas → Ranger flow.

## Local devenv (target)

| Service | Port / endpoint | Notes |
|---------|-----------------|--------|
| Ranger Admin | **6080** | SIMPLE auth for local dev |
| TagSync | background process | REST source → Atlas `:21010` |
| Postgres | `localhost:5455/ranger` | admin + audit schema |

Kerberos (when enabled): realm `DEV.VISTA.ZNDX.ORG`, host
`tinybox.dev.vista.zndx.org` (HTTP SPN for SPNEGO).

## Status

**Near-term / in progress** — submodule at `components/ranger` (`rch/asf-ranger`,
branch **`rch/devenv`**). Config scaffold under `config/ranger/`. Full admin +
TagSync + Impala plugin wiring is part of the current stack plan.

## Build (local, not Impala CDP package)

Impala’s toolchain can download a prebuilt CDP Ranger admin. **Signals does not use that.**
We build `components/ranger` and point Impala at it:

```bash
git submodule update --init components/ranger
devenv tasks run ranger:db-setup
devenv tasks run ranger:build      # today: devenv jdk11 → .devenv/m2
devenv tasks run ranger:install    # .devenv/ranger/admin (not a system package)
```

`config/impala/impala-config-local.sh` sets `RANGER_VERSION_OVERRIDE` + `RANGER_HOME_OVERRIDE`
so bootstrap skips the CDP tarball and the FE resolves plugins from **`.devenv/m2`**.

## JDK / Nashorn (interim)

**Today:** `ranger:build` pins devenv **JDK 11** because parts of the current Ranger
tree still rely on **Nashorn** (`jdk.scripting.nashorn`), which was removed from the
JDK after 14. That is a *local build constraint*, not a product goal.

**Direction:** when appropriate, move the `rch/asf-ranger` / **`rch/devenv`** line
forward to **drop Nashorn** and build/run on **modern JDKs** (align with host
Java 21 / the rest of asf-signals). Until then, treat jdk11 as an explicit
exception in devenv tasks—do not normalize “Ranger needs system JDK 11” as the
long-term model.
