# Summary

# Overview

- [Introduction](./introduction.md)
- [Quick Start](./quickstart.md)

# Architecture

- [System Overview](./architecture/overview.md)
- [Signals protocol core](./architecture/signals-protocol-core.md)
- [Signals engine](./architecture/grpc-engine.md)
- [YuniKorn queue management](./architecture/yunikorn-queue-management.md)
- [Sentinel Applications and Yield](./architecture/sentinel-yield.md)
- [IT-ops FSM and Brier ledger](./architecture/ops-fsm.md)
- [Platform Metaflow](./architecture/metaflow-platform.md)
- [Critical plane](./architecture/stack-critical-plane.md)
- [Query Engine & Catalog Stack](./architecture/query-engine.md)
- [Data Products History](./architecture/data-product-history.md)
- [Data Flow](./architecture/data-flow.md)
- [OpenLineage + Atlas](./architecture/openlineage-atlas.md)
- [Atlas → Kudu outbox](./architecture/atlas-kudu-outbox.md)
- [Governance scale plane](./architecture/governance-scale-plane.md)
- [Signals Control Plane UI](./architecture/signals-control-plane-ui.md)
- [Identity and access](./architecture/identity-and-access.md)
- [Deployment Modes](./architecture/deployment.md)

# Classification

- [Metadata Tagging](./architecture/meta-tagging.md)
- [Context Engineering](./architecture/context-engineering.md)
- [Classification Training](./architecture/classification-training.md)
- [Heuristic Elucidation](./architecture/heuristic-elucidation.md)
- [Evidence Fusion](./architecture/evidence-fusion.md)
- [Bootstrap Agent](./architecture/bootstrap-agent.md)

# Scenarios

- [Scenarios Overview](./scenarios/overview.md)
- [Test Infrastructure](./scenarios/testing.md)
- [Backlog]()
    - [S01: Agent-Mediated Visualization](./scenarios/s01-visualization.md)
    - [S02: Algorithm Extension](./scenarios/s02-extension.md)
    - [S03: Agent Self-Improvement](./scenarios/s03-evolution.md)
    - [S04: OTel Root Cause Analysis](./scenarios/s04-otel-rca.md)
    - [S05: Cybersecurity Investigation](./scenarios/s05-cybersec.md)
    - [S06: Streaming Ontology](./scenarios/s06-streaming.md)

# Infrastructure

- [Infrastructure Overview](./infrastructure/overview.md)
    - [OpenTofu (AWS)](./infrastructure/tofu.md)
    - [Ansible Roles](./infrastructure/ansible.md)
    - [Air-Gap (Zarf)](./infrastructure/zarf.md)
    - [signals-federation (Zarf)](./infrastructure/signals-federation-zarf.md)
    - [Dev Iteration (Tilt)](./infrastructure/tilt.md)
    - [Policy (OPA)](./infrastructure/policy.md)

# Components

- [Components Overview](./components/overview.md)
    - [signals-protocol](./components/signals-protocol.md)
    - [Atlas](./components/atlas.md)
    - [Marquez](./components/marquez.md)
    - [Ranger](./components/ranger.md)
    - [Kudu](./components/kudu.md)
    - [Impala](./components/impala.md)
    - [Impala FDW](./components/impala_fdw.md)
    - [Iceberg](./components/iceberg.md)
    - [Polaris](./components/polaris.md)
    - [YuniKorn](./components/yunikorn.md)
    - [Airflow](./components/airflow.md)
    - [Metaflow](./components/metaflow.md)
    - [Hermes Agent](./components/hermes-agent.md)
    - [MiNiFi C++](./components/minifi-cpp.md)
    - [NiFi](./components/nifi.md)

# Operations

- [Operations Guide](./operations/overview.md)
    - [Development Environment](./operations/devenv.md)
    - [Peer integration](./operations/peer-integration.md)
    - [Peer data products](./operations/peer-data-products.md)
    - [Peer unit acceptance spec](./operations/peer-unit-spec.md)
    - [Storage and backup](./operations/storage-and-backup.md)
    - [Secrets](./operations/secrets.md)
    - [Services](./operations/services.md)
    - [Kerberos](./operations/kerberos.md)
    - [Headless browser (UI verify)](./operations/ui-browser.md)

# Related surfaces

- [WASM Terminal](./architecture/wasm-terminal.md)
- [Visualization Pipeline](./architecture/visualization.md)

# Reference

- [SIGDG Ontology](./reference/sigdg-ontology.md)
- [Configuration](./reference/configuration.md)
- [Research Roadmap](./reference/research-roadmap.md)
- [Roadmap](./reference/roadmap.md)
