# peer-unit-spec — Gaius amendments

**Date:** 2026-08-13

## Collaboration

Gaius peer session amended the shared checklist from
`docs/current/src/operations/peer-unit-spec.md` and product SoR
`gaius/docs/current/src/operations/peer-unit.md`. Signals docs folded those
lessons into peer-integration § Gaius + common pattern.

## Session facts (beyond blank template)

- TCP listen on :50051 ≠ Engine/Status (native service predates the lattice face)
- Third servicer beside GaiusService + OIP; Status at gRPC bind (not vLLM ready)
- stop must not teardown / GPU-wipe siblings
- accept = lattice-ci, not smoke; reflection optional (proto fallback)
- FEDERATION.md is the mesh, not the accept gate (use peer-unit.md)
- Unit enabled; live engine recycle still required for Accept checkboxes

## Live (this host at doc write)

- `gaius.service` enabled, inactive until start after recycle
- `just lattice-ci --require gaius` → FAIL Status RPC (pre-change process on :50051)
- metabase :50451 PASS

## Operator closeout

```bash
# recycle gaius-engine from the zndx/gaius checkout, then:
sudo systemctl start gaius   # or signals.target
just lattice-ci --require gaius
```
