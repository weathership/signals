# Hermes Agent submodule + Weathership memory direction

**Date:** 2026-08-08

## Landed

- Submodule: `components/hermes-agent` → `git@github.com:zndx/oss-hermes-agent.git`
  (pin `06d8aa72e1…` on `main` at add time)
- Docs: `docs/current/src/components/hermes-agent.md`
- Protocol core + components overview updated (P7: Weathership memory/context)

## Why

Signals / Weathership must ship **exceptional** Hermes plugins for:

1. **Memory** — `MemoryProvider` under Hermes’s exclusive memory loader  
   ([memory providers](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers))
2. **Compaction** — context engine  
   ([plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins) /
   context-engine developer guide)

Goal: Weathership becomes an **official reasoning-enabled memory service
provider** in the Hermes ecosystem (same tier as Honcho, Mem0, OpenViking, …).

## Design constraints

| Do | Don't |
|----|--------|
| Back memory with Signals AGE/OL + governance | Second greenfield memory SoR |
| One active provider: `memory.provider: weathership` (name TBD) | Fork Hermes core for discovery |
| Emit OL on memory writes / model ops | Skip authz (Ranger / edge) |
| Pre-compression extract into memory | Lose high-value turns on compact |

## Implementation sketch (later)

```text
src/signals/hermes/   or   plugins/hermes/weathership/
  memory/weathership/     # MemoryProvider subclass
  context_engine/...      # compaction engine
```

Install path: pip entry point and/or symlink into
`~/.hermes/plugins/memory/weathership` and
`plugins/context_engine/…` against `components/hermes-agent` as API reference.

## Upstream plugin layouts (submodule)

```
components/hermes-agent/plugins/memory/
  byterover, hindsight, holographic, honcho, mem0, openviking, retaindb, supermemory
components/hermes-agent/plugins/context_engine/
```

Use these as the contract for `MemoryProvider` and context-engine registration.
