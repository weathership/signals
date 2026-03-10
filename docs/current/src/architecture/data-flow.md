# Data Flow

Data flow through the system connects user interaction, the gRPC engine, compute infrastructure, and data sources.

## Instruction Path

```
User (browser)
  │
  ▼
Ghostty WASM Terminal
  │ gRPC bidirectional stream
  ▼
Signals Engine (Rust)
  │
  ├──► Dask Scheduler ──► Dask Workers (distributed compute)
  │         │
  │         ▼
  │    Datashader (rasterize at viewport resolution)
  │         │
  │         ▼
  │    HoloViews (compose visualization)
  │
  ├──► PostgreSQL (AGE graph queries, pg_cron jobs)
  │
  ├──► Kudu / Impala / Iceberg (analytical storage + SQL)
  │
  └──► Extension Registry (custom algorithm modules)
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

S3 buckets store raw data, intermediate results, and model artifacts. In air-gap deployments, an S3-compatible endpoint (MinIO or Zarf internal) replaces AWS S3.

## Response Path

Computed visualizations flow back through the engine to the web client:

1. Dask workers complete computation
2. Datashader rasterizes the result
3. HoloViews composes the view specification
4. Engine streams the update over gRPC
5. Web client renders the visualization in the top panel
