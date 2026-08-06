# System Overview

Signals 360 is built around a gRPC engine that mediates between user interaction (via a WASM terminal) and analytical computation (via the HoloViews/Datashader/Dask stack), backed by Apache data infrastructure.

## Architecture Layers

```d2
direction: down

web: Web Client {
  viz: HoloViews Visualization {
    tooltip: "Datashader-rasterized views\nAgent-mediated data exploration"
  }
  term: Ghostty WASM Terminal {
    tooltip: "User instructions → gRPC → engine"
  }
  viz -> term: {style.stroke-dash: 3}
}

engine: Engine Layer {
  tooltip: "Agent engine (inspired by mistral-vibe)\nExtension registry\nSelf-improvement cycles"
}

compute: Compute Layer {
  tooltip: "Dask distributed\nDatashader\nHoloViews\nAlgorithm extensions"
}

data: Data Infrastructure {
  tooltip: "PostgreSQL (AGE, pg_cron)\nKudu, Impala, Iceberg\nAtlas, Ranger\nAirflow, NiFi"
}

web -> engine: gRPC
engine -> compute
engine -> data
```

## Key Design Principles

**Agent-mediated interaction.** Users don't interact with raw compute APIs. The agent interprets instructions from the terminal, selects appropriate analysis strategies, and directs the visualization pipeline.

**Resolution autoscaling.** Datashader rasterizes data at the current viewport resolution. When users zoom, Dask recomputes the view in parallel, increasing detail as the viewport narrows.

**Multi-persona views.** A single data product supports multiple persona conventions (Data Scientist, Domain Researcher, Quantitative Analyst, Operational Analyst, Business Analyst) through agent-directed layout and metric selection.

**Extension lifecycle.** Algorithm developers package custom Dask-based analysis modules as platform extensions that the agent can invoke in distributed compute contexts.

**HMS-free, no-HDFS query stack.** Impala + **Kudu-only** storage without Hive
Metastore, HDFS, or HBase. Table metadata lives in a PostgreSQL catalog registry
and is loaded from Kudu master. HDFS is not a product tier; longer-term object/block
storage moves toward **rustfs** and **Ceph**. See [Query Engine & Catalog Stack](./query-engine.md).

**Automated metadata governance.** Tables and columns created in Impala are registered in Atlas and automatically classified by an AI/ML service against a controlled sensitivity vocabulary. Classifications drive Ranger tag-based access policies. See [Metadata Tagging](./meta-tagging.md).
