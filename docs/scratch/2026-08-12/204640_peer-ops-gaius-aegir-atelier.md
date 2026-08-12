# Peer integration ops for Gaius / Aegir / Atelier

**Date:** 2026-08-12

## Why

Metabase landed the reference peer unit. Operators need the same ops narrative
for in-org engines so peer sessions can implement wrappers and then
`systemctl start signals.target` brings the full federated group.

## Doc changes

- `docs/current/src/operations/peer-integration.md` — common pattern; Gaius /
  Aegir / Atelier / Metabase ops; end-state one-command
- `docs/current/src/operations/peer-unit-spec.md` — filled accept blocks for
  gaius, aegir, atelier (metabase already done)
- `config/platform/peer-contract.json` — peer notes + doc anchors
- Sample units annotated: temporary `just up` until peer wrappers land

## Peer session order (suggested)

1. Gaius (`:50051`) — product engine, often first co-tenant
2. Aegir (`:50151`) — watch stack-health vs capability engine
3. Atelier (`:50251`) — dual port 50071/50251

## End state

```bash
sudo systemctl start signals.target
just lattice-ci --require gaius,aegir,atelier,metabase
```
