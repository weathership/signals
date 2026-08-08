# BDD scope: agent-memory + agent-context

**Date:** 2026-08-08

## Decision

Yes — scope for now is **only**:

1. `features/agent/agent_memory.feature`
2. `features/agent/agent_context.feature`

Hermes Agent is the **spec validator** (like Marquez for Atlas+OL): contract
client, not SoR. Features name the product; scenarios say “As a Hermes Agent
user” first; non-Hermes clients are commented `@future` placeholders.

Out of scope for this pass: remote ZT epic, full Gaius/Aegir/Atelier loop,
Flink, resource plane — those remain separate features later.
