# Metaflow

Platform Metaflow for Signals — ground-up capability for any federated engine
via [signals-protocol](./signals-protocol.md). **Not** Gaius-owned; **not**
Marquez.

| | |
|--|--|
| Submodule | `components/metaflow` |
| Remote | `git@github.com:weathership/oss-metaflow.git` |
| Branch | **`rch/devenv`** |
| Architecture | [Platform Metaflow](../architecture/metaflow-platform.md) |

## Role

| Concern | Authority |
|---------|-----------|
| Flow authoring / run metadata | Metaflow (this submodule + metadata service) |
| Production DAG schedule | **Airflow** (`components/airflow`) |
| Event / reactive trigger | **Knative Eventing** → Airflow DAG runs |
| Task pods | RKE2 + **YuniKorn** (`@kubernetes`) |
| Artifacts | **RustFS** (S3) |
| Lineage SoR | **Atlas OL** (not Marquez DB, not Metaflow cards alone) |
| Operator UI | **signals-ui** Applications / Queues |

## Customization

Platform patches to Metaflow land on **`rch/devenv`** in
`weathership/oss-metaflow` (same `rch/devenv` convention as other ASF/oss
submodules). Signals pins that branch via `.gitmodules`.

```bash
git submodule update --init components/metaflow
cd components/metaflow && git checkout rch/devenv && git pull
```

## Status

| Phase | State |
|-------|--------|
| Submodule pin | **Added** (`rch/devenv`) |
| Platform metadata service on RKE2 | **M1** — `just metaflow-platform` |
| Airflow + YK | Planned (M2) |
| Knative Eventing bridge | **M3** — `just knative-eventing` · CE → Airflow (no Argo) |

## Lab deploy (M1)

```bash
# PG :5455 + RustFS :9010 up (devenv), RKE2 Ready
just metaflow-platform
just metaflow-platform-status
# → curl http://127.0.0.1:30180/ping

mkdir -p ~/.metaflowconfig
cp config/metaflow/platform.json ~/.metaflowconfig/config.json
export METAFLOW_SERVICE_URL=http://127.0.0.1:30180
```

## Related

- [Platform Metaflow architecture](../architecture/metaflow-platform.md)
- [Airflow](./airflow.md)
- [YuniKorn](./yunikorn.md)
- [signals-federation Zarf](../infrastructure/signals-federation-zarf.md)
