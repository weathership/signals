@agent @context @weathership
Feature: Agent context compaction (Weathership)
  # Product feature: Signals-backed context engine for agents — compact long
  # sessions without losing high-value institutional / estate knowledge.
  # SoR and durable extract: Signals (and Weathership memory), not only the
  # in-process context window.
  #
  # Spec validator (contract client): Hermes Agent context_engine plugins —
  # analogous to Marquez for Atlas+OL. Submodule: components/hermes-agent.
  # Docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins
  # (context engine plugins / context.engine selection).
  #
  # Scenarios are phrased for Hermes Agent users first so the context-engine
  # contract stays honest. Non-Hermes agent users may add scenarios later
  # against this same feature without forking a second compaction product.

  Background:
    Given the Weathership agent-context engine is available for contract tests
    And Weathership memory is available for pre-compression extract when configured

  # ── Contract / engine shape (Hermes as validator) ─────────────────

  @tier-0 @wip
  Scenario: Weathership registers as a Hermes context engine
    When Hermes discovers context engines including Weathership
    Then Weathership appears as a selectable context.engine
    And the engine implements the context-engine contract surface

  @tier-0 @wip
  Scenario: Compaction preserves a path back to durable knowledge
    Given a session context large enough to require compression
    When the Weathership context engine compacts the window
    Then high-value turns are extractable into Weathership memory or Signals SoR
    And the post-compact context remains usable for the next model turn

  # ── As a Hermes Agent user ───────────────────────────────────────

  @tier-0 @wip
  Scenario: As a Hermes Agent user compaction does not drop recallable facts
    Given I am a Hermes Agent user with Weathership context engine and memory enabled
    And the session has established durable facts via Weathership memory
    When context is compacted mid-session
    Then I can still recall those facts after compaction
    # Prefer re-hydrate from memory/SoR over hoping the window retained them

  @tier-1 @wip
  Scenario: As a Hermes Agent user compaction respects authz-scoped context
    Given I am a Hermes Agent user mapped to a governance principal
    And the session context includes only assets I am allowed to read
    When context is compacted
    Then the compacted representation does not introduce Restricted content
    And subsequent tool results remain subject to Ranger policy

  @tier-1 @wip
  Scenario: As a Hermes Agent user compaction leaves provenance
    Given I am a Hermes Agent user with Weathership context engine enabled
    When a compaction cycle runs
    Then an OpenLineage run or equivalent provenance records the compaction job
    And it is attributable to my principal where identity is available

  # ── Future client (explicit placeholder; do not implement yet) ───
  # @tier-0 @wip @future
  # Scenario: As a non-Hermes agent user I use the same context engine SoR path
  #   Given an agent client other than Hermes against Weathership context APIs
  #   When that client compacts a long session
  #   Then durable extract and authz behavior match the Hermes-validated contract
