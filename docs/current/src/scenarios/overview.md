# Scenarios Overview

Signals 360 is organized around six core scenarios spanning two feature sets. These scenarios are captured as BDD features using the behave framework, with placeholder step definitions that will be implemented as the system develops.

## Feature Sets

### Feature Set A: HoloViews / Datashader / Dask Agent

| Scenario | Feature | Description |
|----------|---------|-------------|
| [S01](./s01-visualization.md) | Agent-Mediated Visualization | Interactive exploration through the web terminal with resolution autoscaling and multi-persona views |
| [S02](./s02-extension.md) | Algorithm Extension | Package, deploy, and invoke custom analysis code as platform extensions |
| [S03](./s03-evolution.md) | Agent Self-Improvement | Define performance objectives and iterate toward quantitative improvements |
| [S04](./s04-otel-rca.md) | OTel Root Cause Analysis | Correlate degradation signals with infrastructure changes for evidence-backed RCA |
| [S05](./s05-cybersec.md) | Cybersecurity Investigation | Investigate malicious behavior using correlated log sources and detection logic |

### Feature Set B: Metastore / Streaming Ontology

| Scenario | Feature | Description |
|----------|---------|-------------|
| [S06](./s06-streaming.md) | Streaming Ontology | Ontology-grounded feature discovery from high-velocity streams with human-in-the-loop direction |

## Platform Scenarios

In addition to the six domain scenarios, two platform features validate infrastructure readiness:

| Feature | File | Description |
|---------|------|-------------|
| Platform Services | `features/platform/services.feature` | devenv environment, PostgreSQL extensions, Kerberos KDC |
| gRPC Engine | `features/platform/grpc_engine.feature` | Engine connectivity, health checks, instruction echo |

## Feature Organization

```
features/
├── environment.py                           # Behave hooks + tier system
├── agent/
│   ├── visualization.feature                # S01
│   ├── extension.feature                    # S02
│   ├── evolution.feature                    # S03
│   └── steps/agent_steps.py
├── analytics/
│   ├── otel_investigation.feature           # S04
│   ├── cybersec_investigation.feature       # S05
│   ├── streaming_ontology.feature           # S06
│   └── steps/analytics_steps.py
├── platform/
│   ├── services.feature
│   ├── grpc_engine.feature
│   └── steps/service_steps.py
└── steps/
    └── steps.py                             # Re-exports for behave discovery
```

## Current Status

All step definitions are placeholder (`raise NotImplementedError`). The features document the intended behavior and serve as living specifications that will be implemented incrementally as components are built.

**8 features, 29 scenarios, 135 steps** across three domains.

See [Test Infrastructure](./testing.md) for the tier system and how to run scenarios.
