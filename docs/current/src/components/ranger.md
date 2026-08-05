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
branch `rch/signals`). Config scaffold under `config/ranger/`. Full admin +
TagSync + Impala plugin wiring is part of the current stack plan.

## Build (once submodule initialized)

```bash
git submodule update --init components/ranger
# then: devenv tasks run ranger:build   # when task lands
```
