# Visualization Pipeline

The agent-mediated visualization stack renders in the top half of the web interface:

- **HoloViews** — declarative data visualization
- **Datashader** — server-side rasterization for large datasets
- **Dask** — distributed computation for on-demand view recomputation

The gRPC engine directs this pipeline: when users issue commands in the WASM terminal, the agent recomputes Datashader-rasterized views via Dask and streams updated HoloViews visualizations back to the web client.
