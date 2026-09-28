# DCGM, the warehouse, and agent exchange

One picture of GPU telemetry in a **cluster** — not only this node — through
the Kubernetes DCGM exporter, the Signals federated workspace, and the tiered
warehouse. Hot rows live on a **Kudu cluster**. Settled rows live as
**Parquet** Iceberg data files, and the message-preserving records live as
**Protobuf** objects, on the same object store. Readers use one surface:
PostgreSQL [`impala_fdw`](../components/impala_fdw.md) over Impala views that
union Kudu and Iceberg. Agent exchanges (`hx_exchange`, `hx_reasoning`) stay
on the same `tx_id` and the same clock as the device samples, so an
interactive session or a reinforcement-learning / fine-tune step can be
read back with the watts and faults it caused.

The fence below is plain Mermaid (`flowchart`). GitHub renders it. Copy the
fence, without the `mermaid` tag line, into any renderer that accepts
GitHub's flowchart syntax. Line breaks inside nodes are `<br>`. Subgraph
titles and node labels that contain punctuation are double-quoted. There
is no `%%{init}%%` directive, no HTML beyond `<br>`, and no diagram type
other than `flowchart`.

```mermaid
flowchart TB
  subgraph hosts ["1. System: every GPU node"]
    nodeA["GPU node A<br>NVIDIA driver and NVML"]
    nodeB["GPU node B<br>NVIDIA driver and NVML"]
    nodeN["GPU node N<br>NVIDIA driver and NVML"]
  end

  subgraph k8s ["2. Kubernetes cluster: dcgm-exporter"]
    ds["DaemonSet federation-system/dcgm-exporter<br>one pod on every GPU node<br>namespace federation-system"]
    pod["Privileged pod, hostNetwork, hostPort 9400<br>mounts host /dev, /proc, /sys, libnvidia-ml<br>no GPU token, default scheduler, no TSDB"]
    fields["Prometheus GET /metrics<br>power, energy, util, framebuffer,<br>clocks, temperature, XID, NVLink<br>scrape interval 250ms"]
    svc["Service dcgm-exporter port 9400<br>one endpoint per node"]
    attr["Pod attribution<br>DCGM_EXPORTER_KUBERNETES=true adds<br>pod, namespace, and container labels<br>the shipped manifest sets false and uses hostPort"]
    ds --> pod --> fields --> svc
    fields -.-> attr
  end

  nodeA --> ds
  nodeB --> ds
  nodeN --> ds

  subgraph workspace ["3. Signals Federated Workspace"]
    scrape["Scrape every node endpoint, once per request<br>SIGNALS_DCGM_PROM_URL<br>this node defaults to 127.0.0.1:9400"]
    otlp["Live yield. Not a store.<br>GET :9410/v1/metrics<br>OTLP metrics protobuf schema, JSON on this port<br>503 when the exporter is down"]
    surface["Engine surface kind=telemetry<br>Gaius, Aegir, Atelier, Hermes, Metabase pull it<br>signals-protocol Status.surfaces"]
    ingest["Retained ingest at native precision<br>src 0 is DCGM. No float widening.<br>signal_series maps dcgm_field to series_id"]
    scrape --> otlp --> surface
    scrape --> ingest
  end

  svc --> scrape

  subgraph hx ["4. Agent exchanges"]
    work["Application work on a resource-class leaf"]
    interactive["Interactive session<br>root.internal.inference.instruct<br>reasoning, light, or agent-rtc<br>product peer.agent.trajectories"]
    train["Reinforcement learning or fine-tune<br>root.internal.inference.extract<br>medium, or heavy<br>product aegir.models.bespoke and peers"]
    external["External leaf, zero GPU claim<br>root.external.subscription.rate-limited<br>token-metered or rate-metered<br>hx is still written"]
    yk["YuniKorn Application<br>app-id = federation.workload_id<br>queue = the resource-class leaf<br>claim key federation.zndx.org/gpu"]
    run["Agents/Run on zndx.agent.v1<br>tx_id is RFC 9562 UUIDv7<br>coordination Activity agent_run"]
    exchange["hx_exchange<br>agent, actor, message per utterance"]
    reasoning["hx_reasoning<br>quality, lineage, delta, trace per turn"]
    facts["details facts, column t = tx_id<br>yk_app_id, yk_queue, run_id, model, flow_name"]
    work --> interactive --> yk
    work --> train --> yk
    work --> external --> run
    yk --> run
    run --> exchange
    run --> reasoning
    run --> facts
  end

  yk -.->|"placed on a node and a GPU ordinal"| pod

  subgraph kudu ["5. Kudu cluster — tier 0, hot"]
    masters["Masters, Raft, odd count<br>cluster: 3 masters<br>this node: 1 master, port 7051"]
    tservers["Tablet servers, port 7050<br>cluster replication 3<br>this node: 1 tserver, replication 1"]
    tables["Hot tables, database signals_dataproducts<br>signal_tier0, signal_series<br>tx_tier0, details_tier0<br>hx_exchange_tier0, hx_reasoning_tier0<br>latent_tier0, clt_activation_tier0"]
    bounds["RANGE on epoch_hour, HASH buckets<br>writers INSERT only<br>expire with DROP RANGE PARTITION<br>never DELETE"]
    masters --> tservers --> tables --> bounds
  end

  subgraph ice ["6. Iceberg on object storage — tier 1, settled"]
    polaris["Polaris REST catalog :8181<br>warehouse signals"]
    spec["Iceberg spec, not Protobuf<br>table metadata is JSON<br>manifest list and manifests are Avro"]
    parquet["Parquet data files<br>settled signal, tx, details, hx rows<br>write.format.default = parquet"]
    proto["Protobuf message objects<br>OTLP ExportMetricsServiceRequest<br>zndx.agent.v1 trajectory / AgentEvent"]
    bucket["Object storage, S3 API<br>bucket s3://signals-dataproducts/<br>this node: RustFS :9010"]
    settle["Settle a closed range<br>copy, verify the Impala count, then DROP RANGE<br>products: data-product.tier-upkeep<br>signals: signal_settle / GpuMetricsSettle"]
    polaris --> spec
    spec --> parquet
    spec --> proto
    parquet --> bucket
    proto --> bucket
    settle --> spec
  end

  subgraph ir ["7. Retrieval — impala_fdw over Kudu and Iceberg"]
    pg["PostgreSQL foreign tables<br>Signals :5455, peer example Gaius :5444<br>one Kerberos GSSAPI principal"]
    fdw["impala_fdw<br>server impala_kudu_srv"]
    kscan["access = kudu_scan<br>libkudu_client<br>tier0 INSERT and hot scan<br>bypasses Impala"]
    hsql["access = impala_sql<br>HiveServer2 :21050"]
    impala["Impala cluster<br>statestore, catalogd, impalad<br>HMS-free catalog registry in Postgres"]
    views["Single reader surface<br>views signal, tx, details,<br>hx_exchange, hx_reasoning<br>tier0 UNION ALL tier1<br>where epoch_hour is not still in tier0"]
    caller["Caller does not pick a tier<br>peers, signals-ui, agents"]
    pg --> fdw
    fdw --> kscan
    fdw --> hsql
    hsql --> impala
    impala --> views
    views --> caller
  end

  subgraph corr ["8. Correlation — performance stays on the operation"]
    live["Live OTLP attributes, not warehouse columns<br>gpu.index, gpu.uuid, gpu.hostname, dcgm.field<br>service.name = signals-dcgm"]
    stamp["Control-plane merge key, signals-ui<br>openlineage.runId<br>yunikorn.applicationId<br>otel.trace_id<br>signals.workload_id"]
    keys["Read-time join. No stored foreign key.<br>tx_id = details.t = hx_exchange.tx_id = hx_reasoning.tx_id<br>same epoch_hour<br>signal.ts_ns inside min..max hx ts_ns for that tx<br>signal.gpu is the device, signal.inst the instance<br>src 0 device samples beside src 1 trainer or vLLM<br>latent_tier0.ref and clt_activation_tier0.ref = the trace<br>hx_reasoning.lineage holds the OpenLineage run id<br>hx_reasoning.trace holds the brief or the protobuf URI"]
    live --> stamp --> keys
  end

  ingest -->|"INSERT"| kscan
  exchange -->|"INSERT"| kscan
  reasoning -->|"INSERT"| kscan
  facts -->|"INSERT"| kscan
  kscan <-->|"kudu_scan read and INSERT"| tables
  tables --> settle
  reasoning -.->|"trace URI"| proto
  tables -->|"UNION tier0 fragment"| impala
  parquet -->|"UNION tier1 scan"| impala
  polaris --> impala
  views -->|"SQL rows plus object URI"| keys
  kscan -->|"hot tier0 rows"| caller
  otlp -.-> live
  yk -.-> stamp
  external -.->|"zero GPU claim, so no src 0 rows"| keys

  style hosts fill:#e7f6ec,stroke:#1b7a3a
  style k8s fill:#e7f1fb,stroke:#1d4e89
  style workspace fill:#f8f1e3,stroke:#8a5a00
  style hx fill:#fdecea,stroke:#8a2b2b
  style kudu fill:#f3e8f8,stroke:#5c2d91
  style ice fill:#eef6f8,stroke:#0f5f6b
  style ir fill:#eef0f8,stroke:#24356b
  style corr fill:#fff6e8,stroke:#8a5a00
```

## Two ways out of the exporter

The exporter does not write the warehouse. Nothing in this path is a TSDB.

| Path | What happens | Retained? |
|------|----------------|-----------|
| Live yield | Signals engine `signals.telemetry.dcgm_otel` GETs `/metrics` once per request and returns OTLP JSON on `:9410/v1/metrics`. `Status.surfaces` advertises that URL with `kind=telemetry`. | No. Empty consumer, no work beyond the idle exporter. Down exporter is HTTP 503. |
| Warehouse land | A workspace writer (the Gaius ingest is the reference) parses the same Prometheus text at the field's native width and `INSERT`s `signal_tier0` through `impala_fdw` `kudu_scan`. `signal_series.src = 0` and `dcgm_field` name the DCGM counter. | Yes. Hot on Kudu, then settled. |

`src` on a sample is `0` DCGM, `1` vLLM or trainer, `2` engine, `3` host.
Device cost and application counters share `epoch_hour` and `ts_ns`. They
are not two pipelines.

Tier-0 inserts in this picture are `impala_fdw` `kudu_scan` (the same
foreign tables the hot scan reads). `signals.ops.warehouse.ImpalaWarehouse`
opens HiveServer2 directly; that sidecar is not the pattern drawn here.

## How a sample stays on a session

There is no foreign key from `signal_tier0` to `tx`. Association is a read
over the views in band 7. For one operation:

1. The operation is one `tx_id` (UUIDv7). `tx`, `details.t`, `hx_exchange`, and `hx_reasoning` use that id.
2. `details` for that id names the placement: `yk_app_id` (this is `federation.workload_id` and the YuniKorn application id), `yk_queue`, `run_id`, `model`, `flow_name`.
3. Interactive work and a fine-tune or RL step differ by **queue leaf and product**, not by storage. Interactive leaves are `root.internal.inference.instruct`, `reasoning`, `light`, and `agent-rtc` (Hermes WebRTC, one GPU while the session runs). The trajectory product is `{peer}.agent.trajectories`. Training-shaped work uses `extract`, `medium`, or `heavy` (for example `aegir.models.bespoke`). There is no project queue and no `root.gaius`.
4. An external leaf (`root.external.subscription.rate-limited`, `token-metered`, `rate-metered`) records `hx_*` and claims **no** GPU. It has no `src = 0` rows.
5. YuniKorn places a GPU Application on a node and a device ordinal. The retained sample stores the device as `signal.gpu` and the instance — the node, when the cluster writer stamps one — as `signal.inst`. Hostname and GPU UUID stay on the live OTLP point (`gpu.hostname`, `gpu.uuid`). They are not columns of `signal_tier0`.
6. Device samples for the operation are `signal` rows with `src = 0`, that `gpu` and `inst`, the same `epoch_hour`, and `ts_ns` between the minimum and maximum `ts_ns` of the `hx_*` rows for the `tx_id`. `src = 1` rows in that window are the trainer or vLLM counters beside the device.
7. When the operation recorded model state, `latent_tier0.ref` and `clt_activation_tier0.ref` carry the same trace id. `hx_reasoning.lineage` carries the OpenLineage run id when the review wrote one. `hx_reasoning.trace` carries the brief, or the object URI of the Protobuf trajectory (`zndx.agent.v1`, ATIF on the object plane).
8. The signals-ui merge key `openlineage.runId · yunikorn.applicationId · otel.trace_id · signals.workload_id` is the control-plane name for the same association. `otel.trace_id` is not its own warehouse column.

`hx_exchange.actor` is the speaker (the column is not named `role`). Kudu
string cells used by `hx_*` are capped at 64KiB; a longer trace is the
Protobuf object, and the cell holds the URI.

## Parquet, Protobuf, and the Iceberg spec

Tier-1 **rows** that Impala scans are Parquet data files under the Iceberg
table (`write.format.default=parquet`). Tier-1 **messages** that must stay
in their wire shape are Protobuf objects on the same bucket: an OTLP
metrics export (`opentelemetry.proto.metrics.v1`) and a `zndx.agent.v1`
trajectory. Iceberg finds the Parquet files through JSON table metadata
and **Avro** manifests. Manifests are not Protobuf.

Polaris (`:8181`) is the REST catalog. The bucket is
`s3://signals-dataproducts/`. On this node that API is RustFS `:9010`.

Writers do not `DELETE`. After a closed range is copied and the Impala
count matches, tier upkeep runs `DROP RANGE PARTITION` on the Kudu tables
(`impala_fdw_exec` for the range DDL). The views hide tier-1 hours that
are still present in tier 0, so a settled-but-not-yet-dropped range is
not counted twice.

## This node and a real cluster

The diagram is the cluster. This workstation is the same graph with the
widths turned down.

| Piece | Cluster | This node |
|-------|---------|-----------|
| DCGM | DaemonSet pod on every GPU node; scrape each Service endpoint | `hostPort 9400`, scrape `127.0.0.1:9400` |
| Exporter labels | Set `DCGM_EXPORTER_KUBERNETES=true` so a sample names the pod | Shipped manifest sets `false` (node-scoped watts) |
| Kudu | 3 masters, tablet servers, replication 3 | 1 master `:7051`, 1 tserver, `kudu.num_tablet_replicas=1` |
| Object store | S3-compatible bucket `signals-dataproducts` | RustFS `:9010` |
| Catalog | Polaris REST | Polaris `:8181` / admin `:8182` |
| SQL front door | Postgres + `impala_fdw` on each peer | Signals `:5455`, Gaius `:5444` |
| Identity | Kerberos GSSAPI, one principal through Postgres, Impala, and Kudu | Realm `DEV.VISTA.ZNDX.ORG` |

The lab settle writer (`scripts/signal_settle.py`,
`scripts/gpu_metrics_tier_up.py`) still emits **HDF5** (`.h5`,
`FileFormat.HDF5`, `write.format.default=hdf5` on `signal_tier1`) and
Impala reads those files with the in-fork HDF5 scanner. That is the
workstation analog. It is not the layout drawn above. The cluster
blueprint's scanned files are Parquet; Protobuf is the message objects
beside them.

## Where the names are defined

| Name in the diagram | Defined in |
|---------------------|------------|
| `dcgm-exporter` DaemonSet, counters, `:9400` | `zarf/federation/manifests/telemetry/dcgm-exporter.yaml` |
| OTLP yield `:9410/v1/metrics` | `src/signals/telemetry/dcgm_otel.py` |
| Telemetry surface | `src/signals/engine/s2s.py` (`kind=telemetry`) |
| `signal_tier0` / `signal` foreign tables | `config/platform/signal-fdw.sql` |
| `tx` / `details` / `hx_*` views | `config/platform/data-products-views.sql` |
| Tier-0 DDL, week ranges, no `DELETE` | `config/platform/data-products-kudu.sql` |
| Resource-class leaves | `config/scheduler/resource-classes.md` |
| `tx_id`, `hx_*`, trajectory product | `components/signals-protocol/specification/protocol/data_products.md`, `agent_grpc.md` |
| FDW `kudu_scan` vs `impala_sql` | [Impala FDW](../components/impala_fdw.md), [Query engine](../architecture/query-engine.md) |

Logical warehouse names and the fact-log shape:
[Data products history](../architecture/data-product-history.md).
The exporter's place on the critical plane:
[Critical plane](../architecture/stack-critical-plane.md).
