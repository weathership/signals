# Brass-tacks naming heuristic

**Date:** 2026-08-13

## Heuristic

Name platform, wire, and **foundational theory** by the terms a practitioner
(or inventor) already uses — not by product metaphor, softened ops slang, or
in-house glosses that drift from the definition.

**Two tests** (fail either → rename until both pass, then document once):

1. **Systems:** Can someone who only knows the underlying tech (gRPC, systemd,
   CI) map the phrase to a concrete artifact without a project glossary?
2. **Theory:** Would the inventors / standard formalizers of the concept
   recognize our names, types, and invariants as *their* object?

### Theory test (worked example)

If Gunnar Carlsson (or any TDA practitioner) reads `signals.persistence` and
callers, precise definitions and implementations should be clear: Vietoris–Rips
filtration, homology dimension (`maxdim`), birth/death diagrams (`dgms`),
essential classes (`death == +inf`), filtration radius (`thresh`) — aligned with
Ripser / literature, not rebranded “topology vibes.” Same bar for
Dempster–Shafer (Bel/Pl/K), SAGE, TreeSHAP, Ollivier–Ricci, etc.

Existing good fit: `src/signals/persistence.py` documents the Ripser API as
canonical and keeps the protocol close to that surface.

## Recent applications (systems)

| Prefer | Avoid | Concrete artifact |
|--------|-------|-------------------|
| multi-service gRPC | multi-face gRPC | One listen port; native + `zndx.engine.v1` [+ OIP] + reflection registered on one server |
| lattice-ci / `*-ci` | smoke (elevated gates) | `just lattice-ci`, `just data-plane-ci`, CE/DAG `*.ci.*` |
| protocol / codegen path | proto fallback | First-party Status via generated stubs; reflection for external grpcurl only |
| peer-scoped stop | soft stop | `systemctl stop <peer unit>` — full stop, peer-scoped, not host teardown |

## Home

Canonical short form: `docs/current/src/architecture/signals-protocol-core.md`
§ Language: brass-tacks naming.

Related: smoke→CI user rule; peer-scoped stop note `031200_peer-scoped-stop-not-soft.md`.
