# Components Overview

Apache and sibling trees live as git submodules under `components/`.
ASF forks track **`rch/devenv`**. Signals pins SHAs from that line.

| Component | Purpose |
|-----------|---------|
| [signals-protocol](./signals-protocol.md) | Shared `zndx.engine.v1` / `scheduler.v1` (`trunk`) |
| [Atlas](./atlas.md) | Governance + OpenLineage REST; AGE on `:21010` |
| [Marquez](./marquez.md) | OpenLineage UI; proxies Atlas `/api/v1` (`:21011`) |
| [Ranger](./ranger.md) | Tag-based authz from Atlas classifications |
| [Kudu](./kudu.md) | Hot-tier columnar store |
| [Impala](./impala.md) | SQL across Kudu and Iceberg |
| [Impala FDW](./impala_fdw.md) | PostgreSQL → Impala HS2 / `kudu_scan` |
| [Iceberg](./iceberg.md) | Warm tier on RustFS |
| [Polaris](./polaris.md) | Iceberg REST catalog (`rch/asf-polaris`) |
| [YuniKorn](./yunikorn.md) | Application admission and queues |
| [Airflow](./airflow.md) | Coordination Activities and Metaflow DAGs |
| [Metaflow](./metaflow.md) | Platform metadata + `@kubernetes` tasks |
| [Hermes Agent](./hermes-agent.md) | Agent peer pin (`zndx/oss-hermes-agent`) |
| [MiNiFi C++](./minifi-cpp.md) | Sentinels (C2 + OTel) on Knative |
| Signals Control UI | Primary backplane, `:9889` (`weathership/signals-ui`) |
| [NiFi](./nifi.md) | Flow routing (planned) |

```bash
git clone --recurse-submodules git@github.com:weathership/signals.git
git submodule update --init --depth 1
```

`impala_fdw` is `weathership/impala_fdw` (`trunk`). Marquez is
`zndx/oss-marquez`. signals-protocol is `zndx/signals-protocol`
(`trunk`). Hermes is `zndx/oss-hermes-agent`. MiNiFi is
`weathership/oss-minifi-cpp`.

C++ builds (Kudu, Impala) need cmake, ninja, gcc, protobuf,
flatbuffers, cyrus_sasl, openssl — all in devenv. The FDW needs
PostgreSQL 16 headers (`pg_config`).
