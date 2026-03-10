# S01: Agent-Mediated Visualization

> Feature Set A — `features/agent/visualization.feature`

## Intent

A user interacts with the agent through the web terminal. The agent directs HoloViews/Datashader/Dask visualizations so the user can explore data interactively with resolution autoscaling and persona-appropriate views.

## Scenarios

### User issues command via WASM terminal
**Tier 2** `@engine-required`

The user connects to the web terminal and submits an instruction. The instruction is delivered to the engine via gRPC and the agent acknowledges the request.

This validates the basic instruction path: terminal → gRPC → engine → acknowledgement.

### Agent recomputes visualization on interaction
**Tier 3** `@viz-required`

Given an active HoloViews session, user interaction with a visualization component triggers Dask to recompute the view in parallel. Datashader rasterizes the updated result and the visualization streams to the web client.

### Resolution autoscaling on zoom
**Tier 3** `@viz-required`

When the user changes the zoom level on a Datashader-rendered view, the view recomputes at the new resolution. Detail increases as the viewport narrows — no raw data is transferred to the client.

### Persona-appropriate view (Scenario Outline)
**Tier 3** `@viz-required`

The agent adapts visualization conventions based on the selected persona. Each persona foregrounds relevant metrics:

| Persona | Emphasis |
|---------|----------|
| Data Scientist | Statistical distributions, feature correlations |
| Domain Researcher | Domain-specific metrics, temporal patterns |
| Quantitative Analyst | Numerical precision, confidence intervals |
| Operational Analyst | System health, throughput, latency |
| Business Analyst | KPIs, trends, executive summaries |

## Capabilities Addressed

From the draft overview:

- Single data product for temporal, spatial, and spectral analysis
- Data resolution autoscaling with active recomputation
- Single data product with visualization for multiple personas
- Base line agent flows
- MLOps for feature extraction, correlation, outlier detection, signals evaluation
