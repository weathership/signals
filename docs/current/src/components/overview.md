# Components Overview

Apache components are tracked as git submodules in `components/`, all on the `rch/signals` branch from `rch` GitHub forks.

| Component | Purpose | Scenarios |
|-----------|---------|-----------|
| [Atlas](./atlas.md) | Metadata governance and data catalog | S06 (ontology) |
| [Ranger](./ranger.md) | Authorization and access control | S05 (cybersec) |
| [Kudu](./kudu.md) | Columnar storage engine | S01, S04 (time-series) |
| [Impala](./impala.md) | Distributed SQL query engine | S04, S05 (analytical queries) |
| [Iceberg](./iceberg.md) | Table format for large analytic datasets | S04, S06 (batch analytics) |
| [Airflow](./airflow.md) | Workflow orchestration | S02, S03 (extension lifecycle) |
| [NiFi](./nifi.md) | Data flow routing and transformation | S06 (stream ingest) |

## Submodule Management

```bash
# Clone with all submodules
git clone --recurse-submodules git@github.com:cldr-research/signals-360.git

# Update submodules to latest rch/signals branch
git submodule update --remote

# Initialize after shallow clone
git submodule update --init --depth 1
```

All submodules are sourced from `rch` GitHub forks with `branch = rch/signals` in `.gitmodules`.

## Build Dependencies

C++ components (Kudu, Impala) require: cmake, ninja, gcc, protobuf, flatbuffers, cyrus_sasl, openssl. These are included in the devenv environment.
