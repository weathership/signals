@agent @memory @weathership
Feature: Agent long-term memory (Weathership)
  # Product feature: Signals-backed reasoning-enabled long-term memory for agents.
  # SoR: Signals (AGE / OL / governance). Not a second memory database.
  #
  # Spec validator (contract client): Hermes Agent MemoryProvider plugins —
  # same role Marquez-web plays for Atlas OpenLineage /api/v1 (UI + contract
  # path, not system of record). Submodule: components/hermes-agent.
  # Docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers
  #
  # Scenario language uses Hermes as the first concrete agent client so the
  # MemoryProvider contract is continuously validated. Non-Hermes agent users
  # may appear later as additional scenarios against the *same* feature
  # (same SoR APIs); they do not redefine the feature.

  Background:
    Given the Weathership agent-memory service is available for contract tests
    And a test principal is known to Atlas and Ranger for memory authz

  # ── Contract / provider shape (Hermes as validator) ──────────────

  @tier-0 @wip
  Scenario: Weathership registers as a Hermes MemoryProvider
    When Hermes discovers memory providers including Weathership
    Then Weathership appears as a selectable memory.provider
    And the provider implements the MemoryProvider contract surface
    # prefetch, turn sync, session extract, search/store tools — per Hermes plugin API

  @tier-0 @wip
  Scenario: Built-in Hermes memory remains additive
    Given Weathership is the active external memory.provider
    When a session uses both built-in MEMORY.md and Weathership
    Then built-in memory continues to function
    And Weathership does not replace built-in files as SoR

  # ── As a Hermes Agent user ───────────────────────────────────────

  @tier-0 @wip
  Scenario: As a Hermes Agent user I can store and recall a fact
    Given I am a Hermes Agent user with Weathership memory enabled
    When I store a durable fact through the Weathership memory tools
    Then a subsequent turn can recall that fact via Weathership search or prefetch
    And the fact is persisted in Signals SoR not only in the Hermes process

  @tier-1 @wip
  Scenario: As a Hermes Agent user my memory writes respect Ranger authz
    Given I am a Hermes Agent user mapped to a governance principal
    And Ranger denies that principal access to Restricted-tagged assets
    When I attempt to store memory derived from a Restricted sample I cannot read
    Then the write is rejected or redacted according to policy
    And no Restricted payload is stored in Weathership memory

  @tier-1 @wip
  Scenario: As a Hermes Agent user memory operations leave OpenLineage provenance
    Given I am a Hermes Agent user with Weathership memory enabled
    When I store and later recall a fact in a session
    Then OpenLineage runs attribute those operations to my principal
    And Atlas GET /api/v1 can list the corresponding job or run namespace

  # ── Future client (explicit placeholder; do not implement yet) ───
  # @tier-0 @wip @future
  # Scenario: As a non-Hermes agent user I use the same memory SoR
  #   Given an agent client other than Hermes against Weathership memory APIs
  #   When that client stores and recalls a fact
  #   Then behavior matches the Hermes-validated contract for the same principal
