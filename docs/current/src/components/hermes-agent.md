# Hermes Agent

Submodule: `components/hermes-agent` →
[`git@github.com:zndx/oss-hermes-agent.git`](https://github.com/zndx/oss-hermes-agent)
(upstream lineage: [NousResearch Hermes Agent](https://hermes-agent.nousresearch.com/)).

## Role in Signals / Weathership

Hermes is the **agent runtime** that multi-agent and operator workflows will
run on (or beside) the Signals stack. Signals does **not** replace Hermes core;
it supplies **exceptional plugins** so agent memory and context compaction are
backed by our SoR, governance, and federation:

| Hermes surface | Signals / Weathership contribution | Official Hermes docs |
|----------------|------------------------------------|----------------------|
| **Memory provider** (`plugins/memory/<name>/`) | Reasoning-enabled long-term memory over Signals (AGE + OL + optional DST outcomes); path to **official memory service provider** listing | [Memory providers](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers) · [Memory provider plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin) |
| **Context engine** (`plugins/context_engine/<name>/`) | Compaction that preserves lineage, tags, and authz-scoped context | [Plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins) · [Context engine plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/context-engine-plugin) |
| General plugins / tools | Atlas/OL/Ranger tools via discovery; OIP model ops with provenance | [Plugins overview](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins) |

Target product name for the official provider: **Weathership** (Signals-backed
reasoning-enabled memory), alongside providers such as Honcho, Mem0, OpenViking,
Hindsight, etc. in Hermes’s memory ecosystem.

## Plugin discovery (Hermes conventions)

From upstream:

- Memory providers: `plugins/memory/<name>/`, subclass `MemoryProvider`; **one**
  active external provider via `memory.provider` in config.
- Context engines: `plugins/context_engine/<name>/`,
  `ctx.register_context_engine(...)`; one active via `context.engine`.
- General tools/hooks: `plugin.yaml` + `register(ctx)` under
  `~/.hermes/plugins/` or project/pip entry points.

Signals-owned plugin code should live **in this monorepo** (e.g.
`plugins/hermes/` or under `src/signals/hermes/`) and install into Hermes
discovery paths — not by forking Hermes memory loaders in the submodule unless
we contribute upstream.

## Submodule use

```bash
git submodule update --init components/hermes-agent

# inspect upstream plugin layouts
ls components/hermes-agent/plugins/memory
ls components/hermes-agent/plugins/context_engine
```

The submodule is the **API and reference implementation** surface (bundled
providers, schemas, loaders). Product plugins that implement Weathership memory
and compaction depend on it and on Signals services (Atlas, `/api/v1`, Ranger,
discovery from [signals-protocol](./signals-protocol.md)).

## Non-goals

- Replacing Hermes with a second agent framework in Signals.
- Shipping a private memory DB that bypasses Atlas/AGE/OL provenance.
- Making Hermes the system of record — **Signals remains SoR**; Hermes is the
  agent client that remembers through us.

## Related

- [Signals protocol core](../architecture/signals-protocol-core.md)
- [OpenLineage + Atlas](../architecture/openlineage-atlas.md)
- [Identity and access](../architecture/identity-and-access.md)
