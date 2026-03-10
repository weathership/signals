# S02: Algorithm Extension Lifecycle

> Feature Set A — `features/agent/extension.feature`

## Intent

An algorithm developer independently develops analysis code leveraging Dask, packages it as a platform extension, and deploys it so the agent can invoke it in distributed compute contexts.

## Scenarios

### Package algorithm as extension
**Tier 0** (pure, no services required)

The developer has a Dask-based analysis module. They package it as a platform extension with valid metadata and a distributable archive. This validates the packaging format without requiring any running services.

### Deploy extension to running platform
**Tier 2** `@engine-required`

A packaged extension is deployed to the platform. The agent registers the new capability and it appears in the capability inventory.

### Agent invokes extension in compute context
**Tier 3** `@engine-required` `@viz-required`

The agent selects a deployed extension for an analysis task. The extension executes within the Dask distributed context and results are surfaced through HoloViews components.

## Draft Scenario Mapping

From the draft overview (Scenario 02):

- Algo dev identifies analysis needs → **Package algorithm as extension**
- Independently develops code leveraging Dask or Ray → **Package algorithm as extension**
- Packages and deploys as platform extension → **Deploy extension to running platform**
- Loads, deploys, tests, and manages the extension → **Deploy extension to running platform**
- Agent includes algorithm as optional capability → **Agent invokes extension in compute context**
