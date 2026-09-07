# Signals

**Federated infrastructure for engines, agents, and data products.**

Signals is the hub of a multi-project federation. Sibling engines — [Gaius](https://github.com/zndx/gaius), [Ægir](https://github.com/zndx/aegir), [Atelier](https://github.com/zndx/atelier), [Hermes Agent](https://github.com/zndx/oss-hermes-agent), and their kin — keep their own products, native gRPC, and models. They meet here: one protocol, one scheduler, one warehouse, one governance record.

If you arrived from [weathership.org](https://weathership.org) or from X, this repository is the station those projects attach to. Clone it to run the lattice, then open any peer and you are already on the same wire.

## Federated

A federated engine is independently operable **and** a full participant. Each process registers the shared [`zndx.engine.v1.Engine`](https://github.com/zndx/signals-protocol) service beside its native service, so a single stub reaches any peer. Capabilities travel on the wire (`cognition`, `instruct`, `referee`, `agent`, `scheduler`); the serving engine chooses the model and reports what it ran.

Gaius is the reference peer: engine-first product logic, pairwise `ServerQuery` (remotes, peers, surfaces, workloads, products, cognition), TTL `Announce` into the directory, `WatchWorkload` for long-held intents, and queue-share occupancy so the hub can see guarantee floors as mix changes. Those shapes landed in Gaius because product work needed them; they now live in signals-protocol so every project can speak them.

Hermes is the agent peer. Interactive WebRTC sessions keep media on the engine (Kyutai STT/TTS) and declare a coordination **Activity** that claims the `agent-rtc` GPU leaf for as long as the session runs. Airflow observes that claim; YuniKorn admits it; the rest of the fleet hears it on the protocol.

```
  Gaius :50051          Ægir :50151         Atelier :50251
  cognition             instruct            referee
         \                   |                   /
          \                  |                  /
           \                 |                 /
            ┌────────────────┴────────────────┐
            │   signals-protocol  (gRPC)      │
            │   zndx.engine.v1 · scheduler.v1 │
            └────────────────┬────────────────┘
                             │
                    Signals engine :50551
                    capability = scheduler
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   YuniKorn :30080     Airflow :30800      Metaflow :30180
   queue admission     Activities / DAGs   platform flows
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
              Kudu + Iceberg + Impala + PostgreSQL
              Atlas / Ranger / OpenLineage
              RustFS  ·  Polaris  ·  signals-ui :9889

  Hermes :50651  (agent)     … Announce into the lattice
```

| Project | Capability | Lattice | Primary UI | Tree |
|---------|------------|---------|------------|------|
| **Signals** (this repo) | `scheduler` | `:50551` | [signals-ui](https://github.com/weathership/signals-ui) `:9889` | [weathership/signals](https://github.com/weathership/signals) |
| Gaius | `cognition` | `:50051` | board `:9890` | [zndx/gaius](https://github.com/zndx/gaius) |
| Ægir | `instruct` | `:50151` | gateway / Vite | [zndx/aegir](https://github.com/zndx/aegir) |
| Atelier | `referee` | `:50251` | workbench `:3000` | [zndx/atelier](https://github.com/zndx/atelier) |
| Hermes Agent | `agent` | `:50651` | dashboard `:9119` | [zndx/oss-hermes-agent](https://github.com/zndx/oss-hermes-agent) |

Launchers never hard-code peer URLs. They seed the hub, read `Engine/Status.surfaces` (`kind=primary`), and walk `ServerQuery PEERS`. A peer **Announces** itself; the waffle fills in.

## Architecture

Signals owns the **critical plane** every federated engine consumes.

| Plane | What lives here | How peers use it |
|-------|-----------------|------------------|
| **Wire** | [signals-protocol](https://github.com/zndx/signals-protocol) pin, codegen, discovery | `Engine/{Status,Complete,Remediate,Yield,ServerQuery,WatchWorkload,Announce,RecordLineage}` |
| **Schedule** | `zndx.scheduler.v1` on `:50551`; YuniKorn is the lab backend | Queues, policy, projection, queue-share, Activities. Clients speak engine gRPC; YuniKorn REST stays private to the scheduler. |
| **Workflows** | Platform [Metaflow](https://github.com/weathership/oss-metaflow) + Airflow 3 + Knative Eventing on RKE2 | Production DAGs, event triggers, run metadata. Artifact store is RustFS. |
| **Storage** | Transparent hierarchical storage: Kudu hot, Iceberg on RustFS, Impala SQL, [impala_fdw](https://github.com/weathership/impala_fdw) from PostgreSQL | Data products (`details` / `tx` / `hx_*`), Atlas/Ranger projections, agent SQL. |
| **Governance** | Apache Atlas (AGE on PostgreSQL 16) + OpenLineage + Ranger | Lineage SoR, classifications, tag-based authz. Marquez-web is the OL UI only. |
| **Control** | [signals-ui](https://github.com/weathership/signals-ui) `:9889` | Queues, applications, sentinels, federated surfaces. |
| **Identity** | Kerberos (data plane) + SecretSpec + Cloudflare Zero Trust (edge) | One principal story into Postgres; the FDW carries it to Impala/Kudu. |

Group lifecycle is `signals.target`: foundation (`just up`) → `signals-ready` → every enabled peer. `just lattice-ci` is the accept gate (generated `Engine/Status` plus server reflection).

```bash
sudo systemctl start signals.target   # foundation + ready + enabled peers
just lattice-ci --require gaius,aegir,atelier
```

## Workloads: YuniKorn, Airflow, Metaflow, and agent-rtc

**YuniKorn** admits **Applications**. The queue path **is** the resource class; project is identity (`federation.project`), not a parent that hoards GPUs. Leaves are shared:

```
root.internal.inference.{reasoning,coding,orchestration,instruct,
                         embedding,heavy,medium,light,extract,agent-rtc}
```

`root.internal.inference.agent-rtc` is the interactive leaf: **one GPU guaranteed**, one Application, fenced, only while a session runs. Hermes packs Kyutai STT onto that GPU; Gaius thinking (TP=4) lives on `heavy`; extract work (OCR, article-curate) has its own floor and can preempt `medium`.

**Airflow** is the federation clock for intent that has a lifetime. A **Coordination Activity** is that intent — owner, reason, horizon, claims, postures — materialised as a Signals-owned DAG run. Topology is two hops:

```
local process  →  peer engine  →  Signals engine :50551  →  Airflow
(interactive,     (Declare /      (lease + sensor)         (the run
 flow, Nautilus)   Renew /                                 is the truth)
                   Release)
```

Only Signals talks to the DAG. `coord_interactive_session` occupies Airflow pool `agent_rtc` (one slot, deferred-inclusive); other kinds run `coord_activity`. The hold task is a deferrable sensor on a Signals lease: heartbeat it, or the horizon expires the intent.

**Metaflow** is the production flow path for every engine that opts in. One metadata service (`:30180`), one S3 datastore on RustFS (`s3://metaflow/metaflow/`), tasks as `@kubernetes` pods YuniKorn admits, DAGs created into Airflow, events through Knative Eventing (`signals-events/default`). Peers copy `config/metaflow/platform.json` and run against that service.

Sentinels **are** Applications. MiNiFi C2 last-gasp becomes `Engine/Yield` so a scale-to-zero proxy returns GPUs through the same contract.

## Transparent hierarchical storage

Percy (2019) described **transparent hierarchical storage**: Kudu for hot mutable rows, Impala for SQL, cooler data as files. That is the warehouse.

| Tier | Store | Role |
|------|--------|------|
| Hot (`*_tier0`) | Apache Kudu | Upserts, current hour, weekly range partitions |
| Warm (`*_tier1`) | Apache Iceberg on RustFS (`s3://signals-dataproducts/`) | Settled weeks (Parquet and HDF5) |
| Read | Impala views (`UNION ALL`) | `details`, `tx`, `hx_exchange`, `hx_reasoning` |
| App / agent SQL | PostgreSQL `:5455` + [impala_fdw](https://github.com/weathership/impala_fdw) | HS2 for shaped SQL; `kudu_scan` via `libkudu_client` for closed governance ops |

Writers insert tier-0. After four weeks the hour-ranges settle to Iceberg and the Kudu range is dropped. Peers publish **facts** (UUIDv7 `tx_id`, product id `{peer}.{domain}.{name}`, RustFS URIs) into the Signals warehouse. Gaius prospects, Metaflow snapshots, and Hermes session artifacts are tenants on that object plane.

PostgreSQL is the front door for AGE, Atlas, Ranger, and agent SQL. Impala remains the analytic engine; the FDW is how applications reach it with one Kerberos principal.

```bash
just impala-fdw-build && just impala-fdw-install
just atlas-kudu-projections-seed     # Atlas typed tables as foreign tables
psql -p 5455 -d signals              # join graph metadata to Kudu rows
```

## signals-protocol

The shared wire is its own repository, vendored here as `components/signals-protocol` and adopted by every peer the same way.

| Package | What it names |
|---------|----------------|
| `zndx.engine.v1` | `Complete`, `Status`, `Remediate`, `Yield`, `ServerQuery`, `RecordLineage`, `WatchWorkload`, `Announce`, Activities |
| `zndx.scheduler.v1` | Queues, policy, projection, `RequestQueueShare`, `Declare/Renew/Release/List/WatchActivity` |
| `zndx.supervision.v1` | Supervision grammar; each project ships a Nautilus *instance* |

Evolution is additive within a version. Changes land in [zndx/signals-protocol](https://github.com/zndx/signals-protocol) first, then propagate by submodule bump — a shared proto is only shared if there is exactly one of it.

```bash
# bump the pin after protocol trunk moves
git -C components/signals-protocol fetch origin
git -C components/signals-protocol checkout origin/trunk
just gen-zndx-engine-py
```

Open Inference Protocol is the horizon mapping for heterogeneous serving (`ModelInfer` ↔ `Complete`). Until a foreign cluster joins, engines federate on this lighter contract.

## Run it

### Prerequisites

- Linux workstation (Impala, Kudu, and the RKE2 critical plane)
- [devenv](https://devenv.sh/) + Nix; [direnv](https://direnv.net/) recommended
- [just](https://github.com/casey/just), `kubectl`, `grpcurl` on `PATH` (systemd units do not inherit the Nix shell)
- Recurse submodules on clone — Apache components and the protocol live there

### First bring-up

```bash
git clone --recurse-submodules git@github.com:weathership/signals.git
cd signals
devenv shell                         # or: direnv allow

# One-time native builds if this machine has never built them
devenv tasks run kudu:build-cpp
devenv tasks run impala:build        # after devenv tasks run impala:bootstrap if needed

cp .env.example .env                 # Kerberos host, data root, optional overrides
just up                              # devenv up -d — full critical plane
just signals-ready                   # PASS/WARN/FAIL; exit 0 when the hub is ready
```

`just up` starts PostgreSQL 16 + AGE (`:5455`), Kerberos, RustFS, Polaris, Atlas, Ranger, Kudu, Impala, signals-ui, and preflights YuniKorn, Knative, Metaflow, and Airflow on RKE2. Open **http://127.0.0.1:9889** — that is the control plane.

```bash
just kinit                           # refresh the lab ticket (principal: signals)
just kerberos-status                 # Impala HS2 GSSAPI OK
just lattice-ci                      # Engine/Status + reflection on the lattice
just test                            # hermetic pytest (tests/)
just behave                          # tier-0 BDD; SIGNALS_BDD_TIER1=1 for the live stack
just docs-serve                      # mdbook at docs/current
```

Group install (lab host with peer checkouts):

```bash
just install-systemd --peers gaius,aegir,atelier --enable
sudo systemctl start signals.target
```

A peer that wants in implements `zndx.engine.v1` on its lattice port, waits on `signals-ready.service`, Announces, and consumes Metaflow, Atlas, and the warehouse as platform services. Contract: [`config/platform/peer-contract.json`](config/platform/peer-contract.json). Walkthrough: [Peer integration](docs/current/src/operations/peer-integration.md).

## Contribute

Signals is the gateway. Work has a home:

| Kind of change | Where it lands |
|----------------|----------------|
| Wire contract (messages, RPCs, specs) | [zndx/signals-protocol](https://github.com/zndx/signals-protocol) — additive PR, then pin here |
| Peer product behaviour | That peer's tree (Gaius cognition, Hermes agent-rtc, Ægir instruct, …) |
| Scheduler, Activities, warehouse, UI, critical plane | **This repository** |
| Impala / Kudu / Iceberg / Atlas / YuniKorn devenv line | `rch/devenv` on the corresponding `rch/asf-*` fork, then bump the submodule |
| FDW | [weathership/impala_fdw](https://github.com/weathership/impala_fdw) (`trunk`) |
| Control UI | [weathership/signals-ui](https://github.com/weathership/signals-ui) |

Inside this tree:

1. `devenv shell` and keep the stack honest (`just up` / `just down` — `just down` releases **this** Postgres on `:5455` only).
2. Put protocol growth in the submodule first; regenerate with `just gen-zndx-engine-py`.
3. Cover lattice behaviour with `tests/signals/` and `just lattice-ci`.
4. Write architecture in `docs/current/src/`; dated lab notes in `docs/scratch/YYYY-MM-DD/`.
5. Apache 2.0, additive public contracts, fail-closed on identity and datastore.

The in-tree `sigint` pipeline classifies columns into the SIGDG taxonomy (Dempster–Shafer fusion, SAGE-measured features) and writes Atlas tags the rest of the federation already consumes.

## Documentation

- [mdbook](docs/current/src/SUMMARY.md) — architecture, components, operations
- [Protocol core](docs/current/src/architecture/signals-protocol-core.md)
- [YuniKorn queue management](docs/current/src/architecture/yunikorn-queue-management.md)
- [Platform Metaflow](docs/current/src/architecture/metaflow-platform.md)
- [Query engine & THS](docs/current/src/architecture/query-engine.md)
- [Data products](docs/current/src/architecture/data-product-history.md)
- [Critical plane](docs/current/src/architecture/stack-critical-plane.md)
- [devenv](docs/current/src/operations/devenv.md)

## License

[Apache License 2.0](LICENSE)
