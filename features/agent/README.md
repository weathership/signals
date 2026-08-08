# Agent features (Weathership)

| Feature | File | Product surface | Contract validator |
|---------|------|-----------------|--------------------|
| Long-term memory | `agent_memory.feature` | Weathership memory SoR (Signals-backed) | **Hermes Agent** `MemoryProvider` |
| Context compaction | `agent_context.feature` | Weathership context engine | **Hermes Agent** `context.engine` |

## Delineation

- **Feature** = product capability of Signals / Weathership (independent of any one agent UI).
- **Scenarios** = currently **As a Hermes Agent user** so Hermes is the living
  **spec validator** (same pattern as Marquez-web for Atlas OpenLineage).
- **Future** = additional scenarios for non-Hermes agent clients against the
  *same* features; do not invent a second memory/context product.

Steps live under `features/agent/steps/` when implementation starts. All
scenarios are `@wip` until Weathership plugins and SoR hooks exist.
