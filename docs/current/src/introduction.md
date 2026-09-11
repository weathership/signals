# Signals

Signals is the hub of a federated compute and data plane. Independent
engines — [Gaius](https://github.com/zndx/gaius),
[Ægir](https://github.com/zndx/aegir),
[Atelier](https://github.com/zndx/atelier),
[Hermes Agent](https://github.com/zndx/oss-hermes-agent) — keep their
own products, native gRPC, and models. They attach here: one protocol,
one scheduler, one warehouse, one governance record.

If you arrived from [weathership.org](https://weathership.org) or from
the GitHub README, this book is the operator and architecture
reference for that hub. Clone this repository, bring the stack up,
and every peer you start is already on the same wire.

## What you get

| Plane | What it is |
|-------|------------|
| **Wire** | [signals-protocol](https://github.com/zndx/signals-protocol) — `zndx.engine.v1` and `zndx.scheduler.v1`. Each engine registers the shared Engine service beside its native service, so one stub reaches any peer. |
| **Schedule** | Signals engine on `:50551` (`capability=scheduler`). [YuniKorn](./architecture/yunikorn-queue-management.md) admits Applications; the queue path is the resource class. |
| **Workflows** | [Airflow](./components/airflow.md) holds coordination Activities (including `agent-rtc`). [Metaflow](./architecture/metaflow-platform.md) is the production flow path: one metadata service, artifacts on RustFS, events through Knative Eventing. |
| **Storage** | Transparent hierarchical storage: Apache Kudu (hot), Apache Iceberg on RustFS (warm), Impala SQL across both, [impala_fdw](./components/impala_fdw.md) from PostgreSQL. |
| **Governance** | Apache Atlas (AGE on PostgreSQL 16) with an OpenLineage REST API. [Marquez-web](./components/marquez.md) is the lineage UI. Ranger consumes Atlas tags. |
| **Control** | [signals-ui](./architecture/signals-control-plane-ui.md) on `:9889`. |

Nautilus sits beside each engine as a deterministic supervisor
(`zndx.supervision.v1`). Classification (`sigint`) still lives in this
tree: it writes SIGDG tags into the same Atlas record the rest of the
federation already uses.

## The lattice

```
  Gaius :50051          Ægir :50151         Atelier :50251
  cognition             instruct            referee
         \                   |                   /
          \                  |                  /
           ┌─────────────────┴─────────────────┐
           │   signals-protocol  (gRPC)        │
           │   zndx.engine.v1 · scheduler.v1   │
           └─────────────────┬─────────────────┘
                             │
                    Signals engine :50551
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   YuniKorn :30080     Airflow :30800      Metaflow :30180
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
              Kudu + Iceberg + Impala + PostgreSQL
              Atlas / Ranger / OpenLineage
              RustFS · Polaris · signals-ui :9889

  Hermes :50651 (agent)     Metabase :50451 (dashboard)
```

| Project | Capability | Port | Primary UI |
|---------|------------|------|------------|
| **Signals** | `scheduler` | `:50551` | signals-ui `:9889` |
| Gaius | `cognition` | `:50051` | board `:9890` |
| Ægir | `instruct` | `:50151` | gateway / Vite |
| Atelier | `referee` | `:50251` | workbench `:3000` |
| Hermes Agent | `agent` | `:50651` | dashboard `:9119` |
| Metabase | `dashboard` | `:50451` | Metabase `:3200` |

A federated engine is independently operable and a full participant.
Capabilities travel on the wire (`cognition`, `instruct`, `referee`,
`agent`, `scheduler`, `dashboard`); the serving engine chooses the
model and reports what it ran. Launchers seed the hub, read
`Engine/Status.surfaces`, and walk `ServerQuery PEERS`. A peer
Announces itself; the Federated menu fills in.

Hermes interactive sessions keep WebRTC media on the engine and
declare a coordination Activity that claims
`root.internal.inference.agent-rtc` — one GPU, only while the session
runs. Airflow observes that claim; YuniKorn admits it.

## Bring it up

Linux workstation, [devenv](https://devenv.sh/) + Nix, recurse
submodules. Impala, Kudu, and the RKE2 critical plane are Linux.

```bash
git clone --recurse-submodules git@github.com:weathership/signals.git
cd signals
devenv shell

# One-time native builds on a fresh machine
devenv tasks run kudu:build-cpp
devenv tasks run impala:build

cp .env.example .env
just up                 # PostgreSQL 16+AGE, Kerberos, RustFS, Polaris,
                        # Atlas, Ranger, Kudu, Impala, signals-ui, …
just signals-ready      # PASS / WARN / FAIL
```

Open **http://127.0.0.1:9889**. Then:

```bash
just kinit
just lattice-ci         # Engine/Status + reflection
just test               # hermetic pytest
just docs-serve         # this book, live
```

Group lifecycle on a lab host:

```bash
just install-systemd --peers gaius,aegir,atelier --enable
sudo systemctl start signals.target
```

Details: [Quick Start](./quickstart.md), [devenv](./operations/devenv.md),
[Peer integration](./operations/peer-integration.md).

## How this book is organized

1. **Architecture** — protocol, queues, Activities, Metaflow, the
   warehouse, Atlas OpenLineage, the control UI.
2. **Components** — the Apache and sibling trees this repo pins.
3. **Operations** — devenv, Kerberos, secrets, backup, joining as a peer.
4. **Classification** — `sigint`, SIGDG, Dempster–Shafer fusion, SAGE.
   Useful if you tag columns; optional if you are attaching an engine.
5. **Reference** — configuration, ontology, roadmaps.

Start with [System Overview](./architecture/overview.md) if you want
the diagram, or [signals-protocol](./architecture/signals-protocol-core.md)
if you are implementing a peer.
