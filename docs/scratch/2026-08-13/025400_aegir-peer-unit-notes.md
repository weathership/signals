# Aegir peer-unit implementation notes

**Date:** 2026-08-13  
**Live:** `lattice-ci --require gaius,aegir,metabase` → PASS (codegen + reflection)

## What landed well

1. **Engine-only unit** — clearest separation yet: lattice start is
   `python -m aegir.engine.server`, not the product `just up` graph. Gateway/vite
   remain optional product UX.
2. **No engine-supervise in the unit** — avoids blocking on vLLM SERVING; Status
   at gRPC bind matches Gaius “Status early, models later.”
3. **Codegen Status + reflection** — both required surfaces green.
4. **Soft stop + dual-bind guard** — co-tenancy lessons from Gaius applied.
5. **Product SoR** — `docs/current/src/operations/peer-unit.md` in Ægir tree.

## Residual / hygiene

- **Commit Ægir tree** peer files if still untracked (`scripts/systemd_*`,
  `zndx_status_ok.py`, `peer-unit.md`, `server.py` reflection, tests).
- **Gaius still shows multi-listen on :50051** in some scans — dual-bind hygiene
  remains an ops watch item on that peer, not introduced by Ægir.
- **Atelier next** — copy Ægir’s engine-only unit pattern; accept on `:50251`
  not product `:50071`.

## Unit model comparison

| Peer | Unit starts | Lattice port |
|------|-------------|--------------|
| Gaius | devenv / gaius-engine process graph | 50051 |
| Ægir | standalone `aegir.engine.server` (setsid) | 50151 |
| Metabase | devenv product + mbengine | 50451 |
