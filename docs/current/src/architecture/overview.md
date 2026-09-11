# System Overview

Signals is the federation hub: protocol pin, scheduler, warehouse, and
governance record. Sibling engines attach over
[signals-protocol](./signals-protocol-core.md) and consume this plane.

## Layers

```d2
direction: down

uis: UIs {
  tooltip: "signals-ui :9889\nGaius Ægir Atelier Hermes Metabase"
}

wire: Protocol {
  tooltip: "zndx.engine.v1\nzndx.scheduler.v1"
}

hub: Hub {
  tooltip: "engine :50551\nYuniKorn Airflow Metaflow"
}

store: Warehouse {
  tooltip: "Kudu Iceberg Impala FDW\nAtlas OpenLineage Ranger"
}

uis -> wire
wire -> hub
hub -> store
```

## Planes

| Plane | Role |
|-------|------|
| **Protocol** | Shared `Engine` and `Scheduler` RPCs. Peers keep native gRPC. |
| **Schedule** | YuniKorn admits Applications. Resource class is the queue leaf. Activities are Airflow DAG runs owned by Signals. |
| **Flows** | One Metaflow metadata service; tasks as Kubernetes pods; events via Knative Eventing. |
| **Storage** | Kudu hot, Iceberg on RustFS, Impala views, PostgreSQL via [impala_fdw](../components/impala_fdw.md). |
| **Governance** | Atlas is lineage and classification. OpenLineage REST on the same process. Marquez-web on `:21011` is the UI. |
| **Control** | signals-ui `:9889`. Federated surfaces come from `Engine/Status`. |

Critical-plane services (Postgres, RustFS, Atlas, Ranger, Kudu, Impala,
YuniKorn, Knative, Metaflow, Airflow) come up together. `just up` is
the entry point; `just signals-ready` is the check. See
[Critical plane](./stack-critical-plane.md).

## Workloads

YuniKorn Applications use leaves such as
`root.internal.inference.{reasoning,coding,instruct,heavy,extract,agent-rtc}`.
Project is identity (`federation.project`). Interactive Hermes sessions
claim `agent-rtc` for one GPU while they run.

Coordination Activities are two hops: local process → peer engine →
Signals `:50551` → Airflow. Only Signals talks to the DAG.

## Classification

`sigint` classifies columns into the SIGDG taxonomy (Dempster–Shafer
fusion, SAGE-measured features) and writes Atlas tags. It is one
consumer of the governance record. See
[Metadata Tagging](./meta-tagging.md) and
[Evidence Fusion](./evidence-fusion.md).
