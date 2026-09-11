# Signals engine

The Signals engine is the scheduler-capability process on **`:50551`**.
It implements `zndx.engine.v1.Engine` and `zndx.scheduler.v1.Scheduler`
from [signals-protocol](./signals-protocol-core.md). Product UIs and
peer engines call this process; they do not speak YuniKorn REST or
Airflow HTTP as a product path.

## Responsibilities

- `Engine/Status`, `ServerQuery`, `Announce`, `WatchWorkload`,
  `RecordLineage`, `Yield`
- Queue policy, projection, and `RequestQueueShare`
- `Declare` / `Renew` / `Release` / `List` / `WatchActivity` —
  leases that Airflow sensors hold
- Discovery: `Status.surfaces` and pairwise `PEERS`

## Where it runs

| Mode | Location |
|------|----------|
| devenv | Local process, `:50551` |
| Lab host | `signals.service` under `signals.target` |
| Cluster | Deployment in the Signals namespace; ClusterIP on 50551 |

Health is gRPC `Engine/Status` plus server reflection.
`just lattice-ci` is the accept probe.

```bash
grpcurl -plaintext 127.0.0.1:50551 zndx.engine.v1.Engine/Status
just lattice-ci
```

Primary UI: [signals-ui](./signals-control-plane-ui.md) `:9889`.
Peer engines (Gaius `:50051`, Ægir `:50151`, Atelier `:50251`, Hermes
`:50651`, Metabase `:50451`) register the same Engine face beside
their native service.
