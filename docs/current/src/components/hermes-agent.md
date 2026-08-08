# Hermes Agent

Submodule: `components/hermes-agent` →
[`git@github.com:zndx/oss-hermes-agent.git`](https://github.com/zndx/oss-hermes-agent)
(upstream lineage: [NousResearch Hermes Agent](https://hermes-agent.nousresearch.com/)).

## Role in Signals / Weathership

Hermes is a valuable **agent runtime surface** for multi-agent and operator
workflows. **For now**, we do **not** treat Signals as a fork of Hermes core:
we pin the submodule and ship **exceptional plugins** (memory + compaction)
so Hermes can use Signals as SoR, governance, and federation.

That is a **sequencing** choice, not a ceiling. Surveying the federated
engine-service fleet (Ægir, Atelier, Gaius, Signals stack, and related labs)
shows a **healthy superset** of what Hermes offers today as a product agent.
Weathership may later deepen integration (including deeper core contribution
or a Weathership-hosted agent face) when product timing warrants it—without
abandoning Hermes-compatible plugins or an official memory-provider path.

| Hermes surface | Signals / Weathership contribution | Official Hermes docs |
|----------------|------------------------------------|----------------------|
| **Memory provider** (`plugins/memory/<name>/`) | Reasoning-enabled long-term memory over Signals (AGE + OL + optional DST outcomes); path to **official memory service provider** listing | [Memory providers](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers) · [Memory provider plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin) |
| **Context engine** (`plugins/context_engine/<name>/`) | Compaction that preserves lineage, tags, and authz-scoped context | [Plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins) · [Context engine plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/context-engine-plugin) |
| General plugins / tools | Atlas/OL/Ranger tools via discovery; OIP model ops with provenance | [Plugins overview](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins) |
| **Signal (messenger)** | `signal-cli` in devenv packages; phone via secretspec `SIGNAL_CLI_PHONE` | Hermes gateway/platform once number is linked |

Target product name for the official provider: **Weathership** (Signals-backed
reasoning-enabled memory), alongside providers such as Honcho, Mem0, OpenViking,
Hindsight, etc. in Hermes’s memory ecosystem.

### Signal CLI (operator messaging)

`pkgs.signal-cli` is on the devenv package set so Hermes can message operators
over [Signal](https://signal.org/) once the account is registered:

```bash
# declare in .env / secretspec provider (never commit the number)
# SIGNAL_CLI_PHONE=+1…
# SIGNAL_CLI_CONFIG_DIR=$DEVENV_STATE/signal-cli   # optional
signal-cli -a "$SIGNAL_CLI_PHONE" …               # link device / send as per signal-cli docs
```

Hermes platform wiring is follow-on; the CLI is available in-shell after
`devenv shell`.

## Federation superset (why “for now”)

Hermes is an excellent agent shell and plugin host. The constellation’s
**operating surface** already goes further in directions Hermes may **never**
fully adopt as first-class product:

| Capability class | Where it lives (examples) | Relation to Hermes |
|------------------|---------------------------|--------------------|
| Multi-engine federation (`zndx.engine.v1`, OIP, co-tenancy) | signals-protocol + Ægir / Atelier / Gaius | Hermes can *call* engines; it is not the federation SoR |
| Governance + lineage SoR | Atlas `/api/atlas/*`, OL `/api/v1/*`, Ranger | Hermes consumes via Weathership plugins / tools |
| DST / classification method | Atelier (healthy); sigint outcomes in Signals | Beyond stock Hermes memory providers |
| **Mechanistic interpretability** (SAE / CLT, feature analysis) | Constellation ML/ops labs (nascent) | Optional Hermes skills exist; depth is fleet-side |
| **Topological analysis** (persistent homology, Ollivier–Ricci curvature) | e.g. `signals.persistence` / openph; geometry labs | Structural memory & graph geometry Hermes is unlikely to own end-to-end |

Plugins are the **compatibility bridge** into Hermes users and the official
provider listing. The **superset** stays in federated engines and Signals so
interpretability and topology can grow without waiting on upstream Hermes
roadmap.

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
discovery paths. Prefer upstream contribution for loader changes; deeper
core integration is deferred (**for now**), not forbidden.

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

## Near-term constraints (not permanent non-goals)

- **For now:** no Hermes-core fork for discovery/loaders; plugins first.
- Do not ship a private memory DB that bypasses Atlas/AGE/OL provenance.
- Do not make Hermes the system of record — **Signals remains SoR**; Hermes is
  an agent client (and listing channel) that remembers through us.
- Later: optional deeper Weathership agent face or upstream core work if the
  superset (SAE/CLT, topology, federation) needs a first-class home beyond
  plugins.

## Related

- [Signals protocol core](../architecture/signals-protocol-core.md)
- [OpenLineage + Atlas](../architecture/openlineage-atlas.md)
- [Identity and access](../architecture/identity-and-access.md)
