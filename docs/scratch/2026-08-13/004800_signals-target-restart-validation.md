# Validate `systemctl restart signals.target`

**Date:** 2026-08-13  
**Objective:** Full group restart works; intermediate Status/reflection gaps resolved.

## Result: PASS

| Check | Outcome |
|-------|---------|
| `systemctl restart signals.target` | exit 0 |
| `signals.service` / `signals-ready` | active, READY |
| `gaius.service` | active (exited); Status `project=gaius` |
| `metabase.service` | active; Status `project=metabase` |
| `just lattice-ci --require gaius,metabase` | **OK** (pass=2) |
| bare `grpcurl …:50051 list` | services incl. `zndx.engine.v1.Engine` + reflection |
| bare `grpcurl … Engine/Status` | JSON body without proto flags |

## Issues found and fixed

1. **gRPC reflection missing on Gaius** — code already enabled reflection but
   `grpcio-reflection` was not in the env. Installed into
   `.devenv/state/venv`; bare grpcurl works after engine restart.
2. **Status probes** — unit wrappers require a real Status body; lattice-ci
   uses **gRPC server reflection** (now a signals-protocol install requirement).
3. **Dual/triple listeners on :50051** — orphan engines from prior devenv
   sessions + unit start made Status flaky (one process had lattice face, one
   did not). Killed orphans; start script warns and best-effort TERMs extra
   `gaius.engine` PIDs when `ss` shows multiple listeners.

## Ops notes

- Full target restart stops foundation (`just down`) then peers; ~1–2+ min when
  stacks are warm, longer cold.
- **Reflection is required** on lattice ports (install `grpcio-reflection` /
  enable ServerReflection). That is the accept path we define — not optional DX.
- Core vs license-external: Metabase remains isolated AGPL peer; process group
  co-start does not change architecture class.

## Peer tree changes (not in signals commit)

- `zndx/gaius/scripts/systemd_start.sh` — proto fallback, project=gaius check, dual-bind guard
- `zndx/gaius/pyproject.toml` — `grpcio-reflection>=1.59.0`
- `agpl/metabase/scripts/systemd_start.sh` — proto fallback for Status
