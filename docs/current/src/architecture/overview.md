# System Overview

Signals 360 is built around a gRPC engine that mediates between user interaction (via a WASM terminal) and analytical computation (via the HoloViews/Datashader/Dask stack), backed by Apache data infrastructure.

## Architecture Layers

```
┌─────────────────────────────────────────────────────┐
│  Web Client                                         │
│  ┌───────────────────────────────────────────────┐  │
│  │  HoloViews Visualization (top half)           │  │
│  │  - Datashader-rasterized views                │  │
│  │  - Agent-mediated data exploration            │  │
│  ├───────────────────────────────────────────────┤  │
│  │  Ghostty WASM Terminal (bottom half)          │  │
│  │  - User instructions → gRPC → engine          │  │
│  └───────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────┘
                       │ gRPC
┌──────────────────────▼──────────────────────────────┐
│  Engine Layer (Rust)                                │
│  - Agent engine (inspired by mistral-vibe)          │
│  - Extension registry                               │
│  - Self-improvement cycles                           │
└──────────┬─────────────────────┬────────────────────┘
           │                     │
┌──────────▼──────────┐  ┌──────▼─────────────────────┐
│  Compute Layer      │  │  Data Infrastructure        │
│  - Dask distributed │  │  - PostgreSQL (AGE, pg_cron)│
│  - Datashader       │  │  - Kudu, Impala, Iceberg    │
│  - HoloViews        │  │  - Atlas, Ranger            │
│  - Algorithm exts   │  │  - Airflow, NiFi            │
└─────────────────────┘  └────────────────────────────┘
```

## Key Design Principles

**Agent-mediated interaction.** Users don't interact with raw compute APIs. The agent interprets instructions from the terminal, selects appropriate analysis strategies, and directs the visualization pipeline.

**Resolution autoscaling.** Datashader rasterizes data at the current viewport resolution. When users zoom, Dask recomputes the view in parallel, increasing detail as the viewport narrows.

**Multi-persona views.** A single data product supports multiple persona conventions (Data Scientist, Domain Researcher, Quantitative Analyst, Operational Analyst, Business Analyst) through agent-directed layout and metric selection.

**Extension lifecycle.** Algorithm developers package custom Dask-based analysis modules as platform extensions that the agent can invoke in distributed compute contexts.
