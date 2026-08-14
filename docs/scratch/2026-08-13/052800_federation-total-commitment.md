# Doctrine: total commitment as a federation peer

**Date:** 2026-08-13

## Statement

Adopting **signals-protocol** as a federation peer is **total commitment**:

1. **Full engine capacity** — real capability engine for that project, not a
   lattice-only shell.
2. **Honest operational transitions** — start / stop / restart fully effect the
   intended process state (or it is an error requiring remediation).
3. **Remediation** — peers already own this (e.g. Gaius health/FMEA /
   `/health fix engine`); do not paper over faults with optimistic Status.
4. **Hub sequencing (not “thin forever”)** — Signals is **early** on the engine
   axis: federation architecture is still being nailed down, so little engine
   surface lives here *yet*. That is maturity, not a permanent ban. Peers own
   depth and lifecycle honesty on their lattice ports today.

## Motivation

Lab `signals.target` restart (2026-08-13) showed Gaius can pass lattice-ci while
orphans / multi process-compose / synthetic always-healthy Status weaken true
start/stop/restart. Aegir/Atelier engine-only units behaved closer to doctrine.

## Homes

- `docs/current/src/architecture/signals-protocol-core.md`
  § Doctrine: total commitment as a federation peer
- `docs/current/src/operations/peer-unit-spec.md` (Must / Accept checklist)
- `docs/current/src/operations/peer-integration.md` (common peer unit pattern)

## Follow-ups (peer trees, not this note)

- Gaius: honest Status (drop synthetic always-healthy cognition); stop frees
  port + foreign process-compose; restart under unit only.
- Keep peer remediation paths as the recovery surface for transition failures.
