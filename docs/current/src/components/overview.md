# Components Overview

Apache components are tracked as git submodules in `components/`, all on the `rch/signals` branch from `rch` GitHub forks.

| Component | Purpose | Status |
|-----------|---------|--------|
| [Impala](./impala.md) | Distributed SQL query engine (HMS-free) | **Running** — DDL, DML, JOINs, aggregations |
| [Kudu](./kudu.md) | Columnar storage engine (hot tier) | **Running** — master + tserver (build from `components/kudu`) |
| [Atlas](./atlas.md) | Metadata catalog + AI-driven classification | **Running** — AGE backend on `:21010` |
| [Impala FDW](./impala_fdw.md) | Postgres → Impala HS2 foreign data wrapper | Scaffold — HS2 scans not yet implemented |
| [Iceberg](./iceberg.md) | Table format via Polaris REST catalog (warm tier) | Near-term — REST API implemented |
| [Ranger](./ranger.md) | Tag-based access control via Atlas classifications | Near-term — config scaffold in place |
| [Airflow](./airflow.md) | Workflow orchestration | Planned |
| [NiFi](./nifi.md) | Data flow routing and transformation | Planned |

## Submodule Management

```bash
# Clone with all submodules
git clone --recurse-submodules git@github.com:cldr-research/signals-360.git

# Update submodules to latest rch/signals branch
git submodule update --remote

# Initialize after shallow clone
git submodule update --init --depth 1
```

Core ASF forks use `rch` GitHub remotes with `branch = rch/signals` in `.gitmodules`.
`impala_fdw` is `weathership/impala_fdw` on branch `trunk`. Openph is optional reference
only (CPU PH uses Ripser via `signals.persistence`).

## Build Dependencies

C++ components (Kudu, Impala) require: cmake, ninja, gcc, protobuf, flatbuffers, cyrus_sasl, openssl. These are included in the devenv environment. Impala FDW needs PostgreSQL 16 dev headers (`pg_config`).
