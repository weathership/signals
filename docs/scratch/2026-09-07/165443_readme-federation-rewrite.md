# README rewrite: Signals as federation hub

GitHub visitors from weathership.org (and X) still landed on the 2025
signals-360 column-classification README. The tree has been the federation
hub for months. This note records what the rewrite is based on.

## Sources

- Hermes (`~/local/src/oss/hermes-agent`): hsengine peer on `:50651`
  (`capability=agent`), engine-local WebRTC + Kyutai STT, coordination
  Activities (`interactive_session` → Signals `:50551` → Airflow pool
  `agent_rtc`), workload catalogue `interactive.agent_rtc`, YK leaf
  `root.internal.inference.agent-rtc` (1 GPU guaranteed while RUNS),
  `Engine/Announce` into directory seeds. Media stays off signals-protocol.
- Gaius: engine-first gRPC, `ServerQuery` kinds (PEERS / SURFACES /
  WORKLOADS / PRODUCTS / COGNITION), `Announce`, `WatchWorkload`,
  `RequestQueueShare`, data-product facts on RustFS, full-stack unit under
  `signals.target`. Those shapes are what pending work in the other trees
  consumes.
- Protocol pin `components/signals-protocol` (and Gaius
  `external/signals-protocol`): engine.v1 + scheduler.v1 + Activities.
- THS: Percy 2019 restated in `architecture/iceberg-hdf5.md` and
  `query-engine.md`; warehouse `details`/`tx`/`hx_*`; `impala_fdw` dual
  path (HS2 + `kudu_scan`).
- Hub surfaces: signals-ui `:9889`, YK `:30080`, Airflow `:30800`,
  Metaflow `:30180`, engine `:50551`.

## What changed in the README

- Title is **Signals**, not signals-360.
- Lead is federation (protocol, scheduler, warehouse, governance), not DST.
- `sigint` remains a short closing note — still in-tree, no longer the
  identity.
- Intended architecture only; no “what we don’t use” curriculum.
- Clone URL is `weathership/signals`.
- Developer path: devenv, `just up`, `signals-ready`, lattice-ci, peer
  attach.

`pyproject.toml` description updated to match (Hatch `readme = "README.md"`).
