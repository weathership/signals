# Visualization Pipeline

The agent-mediated visualization stack renders in the top half of the web interface.

## Stack

| Component | Role |
|-----------|------|
| **HoloViews** | Declarative data visualization — the agent composes views from the [HoloViews gallery](https://holoviews.org/gallery/) |
| **Datashader** | Server-side rasterization for large datasets at viewport resolution |
| **Dask** | Distributed parallel computation for on-demand view recomputation |

## Agent-Mediated Flow

The gRPC engine directs this pipeline. When users issue commands in the WASM terminal, the agent:

1. Interprets the instruction and selects a visualization strategy
2. Directs Dask to perform distributed computation
3. Datashader rasterizes the result at the current viewport resolution
4. Updated HoloViews visualizations stream back to the web client

## Capabilities

### Resolution Autoscaling

Datashader renders data at the pixel resolution of the current viewport. On zoom:

- Dask recomputes the view in parallel over the narrowed data range
- Detail increases as the viewport narrows
- No client-side data transfer — only rasterized images transit the network

### Multi-Persona Views

A single data product supports multiple persona conventions. The agent adjusts layout, metric selection, and visual conventions based on the active persona:

| Persona | Emphasis |
|---------|----------|
| Data Scientist | Statistical distributions, feature correlations |
| Domain Researcher | Domain-specific metrics, temporal patterns |
| Quantitative Analyst | Numerical precision, confidence intervals |
| Operational Analyst | System health, throughput, latency |
| Business Analyst | KPIs, trends, executive summaries |

### MLOps Integration

The visualization pipeline supports:

- Feature extraction and correlation views
- Outlier detection and signal evaluation
- Signal correlation across temporal, spatial, and spectral dimensions
- Labeling workflows for different data modalities
