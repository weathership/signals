# Components Overview

Apache components are tracked as git submodules in `components/`, on the
**`rch/devenv`** branch from `rch` GitHub forks (`rch/asf-*`). That branch is the
shared devenv/Nix-build line for any host product; signals pins SHAs from it.

| Component | Purpose | Status |
|-----------|---------|--------|
| [Impala](./impala.md) | Distributed SQL query engine (HMS-free) | **Running** — DDL, DML, JOINs, aggregations |
| [Kudu](./kudu.md) | Columnar storage engine (hot tier) | **Running** — master + tserver (build from `components/kudu`) |
| [Atlas](./atlas.md) | Metadata catalog + AI-driven classification | **Running** — AGE backend on `:21010` |
| [Impala FDW](./impala_fdw.md) | Postgres → Impala HS2 → **Kudu only**; **FDW-only / no-JDBC** access default | Scaffold — HS2 scans not yet implemented |
| [Iceberg](./iceberg.md) | Table format via Polaris REST catalog (warm tier) | Near-term — REST API implemented |
| [Ranger](./ranger.md) | Tag-based access control via Atlas classifications | Near-term — config scaffold in place |
| [Marquez](./marquez.md) | OL **UI** only (oss-marquez); proxies Atlas `/api/v1` — no Marquez DB | **Default stack** process |
| [signals-protocol](./signals-protocol.md) | Shared federation protos (`zndx.engine.v1`, discovery, OIP mapping) | Submodule pin `trunk` |
| [Hermes Agent](./hermes-agent.md) | Agent runtime; Weathership memory + context-engine plugins | Submodule pin (`zndx/oss-hermes-agent`) |
| [MiNiFi C++](./minifi-cpp.md) | Federation **sentinels** (C2 + OTel) on Knative | Submodule `weathership/oss-minifi-cpp` |
| [YuniKorn](./yunikorn.md) | Required admission/queues for sentinel pods on RKE2 | Submodule `components/yunikorn-core` |
| Signals Control UI | **Primary backplane** — yk-web ⊇ + lineage/sentinels (Rust/Axum :9889) | `components/signals-ui` → `weathership/signals-ui` |
| [Airflow](./airflow.md) | Metaflow production DAGs on RKE2/YK; events via Knative Eventing | Planned — see [Platform Metaflow](../architecture/metaflow-platform.md) |
| [Metaflow](./metaflow.md) | Platform Metaflow (`components/metaflow` → `weathership/oss-metaflow` **`rch/devenv`**) | Submodule pinned; platform deploy M1+ |
| [NiFi](./nifi.md) | Data flow routing and transformation | Planned |

## Submodule Management

```bash
# Clone with all submodules
git clone --recurse-submodules git@github.com:cldr-research/signals-360.git

# Update submodules to latest rch/devenv tip (see .gitmodules branch=)
git submodule update --remote

# Initialize after shallow clone
git submodule update --init --depth 1
```

Core ASF forks use `rch` GitHub remotes with **`branch = rch/devenv`** in
`.gitmodules` (shared devenv/Nix line for any host). `impala_fdw` is
`weathership/impala_fdw` on branch `trunk`. Marquez is `zndx/oss-marquez` on
`main`. **signals-protocol** is `zndx/signals-protocol` on `trunk` (federation
wire contracts — not an ASF fork). **hermes-agent** is
`zndx/oss-hermes-agent` (Hermes Agent fork/pin for memory and compaction
plugins). **minifi-cpp** is `weathership/oss-minifi-cpp` (federation sentinels).
**yunikorn-core** is the YK scheduler pin (admission instance). Openph is optional
reference only (CPU PH uses Ripser via `signals.persistence`).

## Build Dependencies

C++ components (Kudu, Impala) require: cmake, ninja, gcc, protobuf, flatbuffers, cyrus_sasl, openssl. These are included in the devenv environment. Impala FDW needs PostgreSQL 16 dev headers (`pg_config`).
