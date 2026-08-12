# Peer systemd group + external (AGPL) engines

**Date:** 2026-08-12

## Done

1. Commit/push `signals-ready` + CI naming (`b4d1804` on trunk).
2. `config/platform/peer-contract.json` — endpoints, CE map, engine lattice, license boundary.
3. `infra/systemd/` — `signals.target`, foundation, ready oneshot, peer samples including **metabase.service** (external AGPL path).
4. Ops doc `docs/current/src/operations/peer-integration.md`.

## Model

- **Foundation:** ASL2 signals critical plane; ready via `just signals-ready`.
- **Peers (in-org trees):** After ready; consume Metaflow/Airflow/Eventing/YK/Atlas.
- **External AGPL (Metabase):** Same process ordering; **no** source in signals repo; wire = signals-protocol gRPC `:50451` dashboard capability.

## Enable subset

```bash
sudo systemctl enable signals.target signals.service signals-ready.service
sudo systemctl enable gaius.service metabase.service   # example
sudo systemctl start signals.target
```
