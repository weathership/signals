# Signals 360

Signals 360 integrates Apache data infrastructure components with an agent-mediated visualization engine, providing interactive analytical capabilities through a web-based terminal interface.

## Key Capabilities

- **gRPC Engine** — server-side agent engine (Rust) directing analytical workloads
- **WASM Terminal** — browser-embedded Ghostty terminal for interactive commands
- **Visualization Pipeline** — HoloViews/Datashader/Dask stack for agent-mediated data exploration
- **Apache Components** — Atlas, Ranger, Kudu, Impala, Iceberg, Airflow, NiFi
- **Deployment** — AWS, air-gap (Zarf), and Kubernetes orchestration

## Architecture

The web interface presents a split view: a Ghostty WASM terminal (bottom) for user interaction and agent-mediated HoloViews visualizations (top). Instructions transit gRPC between the terminal and the server engine, which directs the Dask/Datashader pipeline to recompute views on demand.
