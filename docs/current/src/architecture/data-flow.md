# Data Flow

Data flow through the system connects user interaction, the gRPC engine, compute infrastructure, and data sources.

## Instruction Path

```d2
direction: down

user: User (browser)
terminal: Ghostty WASM Terminal
engine: Signals Engine

user -> terminal
terminal -> engine: gRPC bidirectional stream

scheduler: Dask Scheduler
workers: Dask Workers {tooltip: "distributed compute"}
datashader: Datashader {tooltip: "rasterize at viewport resolution"}
holoviews: HoloViews {tooltip: "compose visualization"}

pg: PostgreSQL {tooltip: "AGE graph queries, pg_cron jobs"}
analytics: Kudu / Impala / Iceberg {tooltip: "analytical storage + SQL"}
extensions: Extension Registry {tooltip: "custom algorithm modules"}

engine -> scheduler
scheduler -> workers
workers -> datashader
datashader -> holoviews

engine -> pg
engine -> analytics
engine -> extensions
```

## Data Sources

### Streaming Ingest

High-velocity data (click streams, telemetry) arrives via NiFi and is routed to appropriate storage layers. The engine can direct the agent to observe stream accumulation and discover ontology-grounded feature patterns.

### Analytical Storage

| Layer | Engine | Access Pattern |
|-------|--------|---------------|
| Graph | PostgreSQL + AGE | Relationship queries, ontology traversal |
| Columnar | Kudu | Low-latency random access, time-series |
| SQL | Impala | Distributed analytical queries |
| Table Format | Iceberg | Large-scale batch analytics, schema evolution |

### Object Storage

S3 buckets store raw data, intermediate results, and model artifacts. In air-gap deployments, an S3-compatible endpoint (RustFS or similar) replaces AWS S3.

## Response Path

Computed visualizations flow back through the engine to the web client:

1. Dask workers complete computation
2. Datashader rasterizes the result
3. HoloViews composes the view specification
4. Engine streams the update over gRPC
5. Web client renders the visualization in the top panel
