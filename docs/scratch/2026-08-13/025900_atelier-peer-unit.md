# Atelier peer-unit under signals.target

**Date:** 2026-08-13

## Result

`just lattice-ci --require gaius,aegir,atelier,metabase` → **OK**

| Unit | Lattice |
|------|---------|
| atelier.service | :50251 Status + reflection |

## Pattern

Engine-only (Ægir template): `python -m atelier.engine.server`, not product
servicer `:50071` / `just up`. Status advertises referee/instruct at bind.

## Atelier tree files

- `scripts/systemd_{start,stop}.sh`, `zndx_status_ok.py`
- `src/atelier/engine/server.py` — reflection + Status placeholders
- `docs/current/src/operations/peer-unit.md`
- `pyproject.toml` — grpcio-reflection
