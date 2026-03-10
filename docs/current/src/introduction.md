# Signals 360

Signals 360 integrates Apache data infrastructure components with an agent-mediated visualization engine, providing interactive analytical capabilities through a web-based terminal interface.

## Key Capabilities

- **gRPC Engine** — server-side agent engine directing analytical workloads
- **WASM Terminal** — browser-embedded Ghostty terminal for interactive commands
- **Visualization Pipeline** — HoloViews/Datashader/Dask stack for agent-mediated data exploration
- **Apache Components** — Atlas, Ranger, Kudu, Impala, Iceberg, Airflow, NiFi
- **Deployment** — AWS, air-gap (Zarf), and Kubernetes orchestration (4 modes)

## Architecture

The web interface presents a split view: a Ghostty WASM terminal (bottom) for user interaction and agent-mediated HoloViews visualizations (top). Instructions transit gRPC between the terminal and the server engine, which directs the Dask/Datashader pipeline to recompute views on demand.

## Scenarios

The project is organized around six core scenarios across two feature sets:

| # | Scenario | Feature Set |
|---|----------|-------------|
| S01 | [Agent-Mediated Visualization](./scenarios/s01-visualization.md) | A: HoloViews/Datashader/Dask Agent |
| S02 | [Algorithm Extension](./scenarios/s02-extension.md) | A: HoloViews/Datashader/Dask Agent |
| S03 | [Agent Self-Improvement](./scenarios/s03-evolution.md) | A: HoloViews/Datashader/Dask Agent |
| S04 | [OTel Root Cause Analysis](./scenarios/s04-otel-rca.md) | A: HoloViews/Datashader/Dask Agent |
| S05 | [Cybersecurity Investigation](./scenarios/s05-cybersec.md) | A: HoloViews/Datashader/Dask Agent |
| S06 | [Streaming Ontology](./scenarios/s06-streaming.md) | B: Metastore/Streaming Ontology |

These scenarios are captured as BDD features (8 feature files, 29 scenarios, 135 steps) and serve as the living specification for the system.

## Documentation Structure

- **[Architecture](./architecture/overview.md)** — system design, components, data flow
- **[Scenarios](./scenarios/overview.md)** — feature specifications and BDD mapping
- **[Infrastructure](./infrastructure/overview.md)** — deployment, provisioning, configuration
- **[Components](./components/overview.md)** — Apache data infrastructure
- **[Operations](./operations/overview.md)** — development environment, services
- **[Reference](./reference/configuration.md)** — configuration, roadmap
