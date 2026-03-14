@platform @health @atlas
Feature: Atlas metadata governance
  Atlas provides type system, entity catalog, classification, search,
  glossary, and lineage — all backed by PostgreSQL with Apache AGE
  (graph), tsvector (FTI), and pg_trgm (suggestions).

  # ── REST API ──────────────────────────────────────────────────────

  @tier-0
  Scenario: Atlas REST API is accessible
    When I call the Atlas version endpoint
    Then the response status is 200
    And the response contains a version string

  # ── PostgreSQL FTI schema ─────────────────────────────────────────

  @tier-0
  Scenario: Atlas FTI schema exists in PostgreSQL
    When I connect to the "signals" database
    Then table "atlas_fti_vertex" exists
    And table "atlas_fti_edge" exists
    And table "atlas_index_meta" exists

  # ── Type system bootstrap ─────────────────────────────────────────

  @tier-0 @tdd
  Scenario: Bootstrap type definitions are loaded
    When I list Atlas type definition headers
    Then at least 10 type definitions exist
    When I search Atlas for type "Referenceable"
    Then the type definition exists
    When I search Atlas for type "DataSet"
    Then the type definition exists

  # ── Type CRUD ─────────────────────────────────────────────────────

  @tier-0 @tdd
  Scenario: Atlas accepts custom entity type definitions
    When I create Atlas entity type "signals_test_asset" with attributes:
      | name        | type   |
      | name        | string |
      | description | string |
      | score       | float  |
    Then the response status is 200
    When I search Atlas for type "signals_test_asset"
    Then the type definition exists

  # ── Entity CRUD ───────────────────────────────────────────────────

  @tier-0 @tdd
  Scenario: Atlas creates and retrieves entities
    Given Atlas entity type "signals_test_asset" exists
    When I create an Atlas entity of type "signals_test_asset":
      | attribute     | value                   |
      | name          | test-entity-1           |
      | qualifiedName | test://health/entity-1  |
      | description   | BDD health check entity |
    Then the entity is created successfully
    When I retrieve the Atlas entity by qualifiedName "test://health/entity-1"
    Then the entity attribute "name" is "test-entity-1"

  # ── Classification ────────────────────────────────────────────────

  @tier-0 @tdd
  Scenario: Atlas creates and applies classifications
    Given Atlas entity "test://health/entity-1" of type "signals_test_asset" exists
    When I create Atlas classification type "signals_test_pii"
    Then the response status is 200
    When I apply classification "signals_test_pii" to entity "test://health/entity-1"
    Then the entity "test://health/entity-1" has classification "signals_test_pii"

  # ── Full-text search (PostgreSQL tsvector) ────────────────────────

  @tier-0 @tdd
  Scenario: Atlas full-text search returns results
    Given Atlas entity "test://health/entity-1" of type "signals_test_asset" exists
    When I perform an Atlas basic search for "test-entity"
    Then the search returns at least 1 result
    And the search results contain entity "test://health/entity-1"

  # ── Suggestions (pg_trgm) ─────────────────────────────────────────

  @tier-0 @tdd
  Scenario: Atlas provides search suggestions
    Given Atlas entity "test://health/entity-1" of type "signals_test_asset" exists
    When I request Atlas suggestions for prefix "test-ent"
    Then the suggestions include "test-entity-1"

  # ── Glossary ──────────────────────────────────────────────────────

  @tier-0 @tdd
  Scenario: Atlas manages glossary terms
    When I create an Atlas glossary "signals_test_glossary"
    Then the glossary is created successfully
    When I create a term "Revenue" in glossary "signals_test_glossary" with description "Total income"
    Then the term is created successfully
    When I retrieve the glossary "signals_test_glossary" with terms
    Then the glossary contains term "Revenue"

  # ── Lineage ───────────────────────────────────────────────────────

  @tier-0 @tdd
  Scenario: Atlas tracks data lineage
    Given Atlas entity "test://health/source-1" of type "DataSet" exists
    And Atlas entity "test://health/target-1" of type "DataSet" exists
    And Atlas entity "test://health/process-1" of type "Process" exists with lineage from "test://health/source-1" to "test://health/target-1"
    When I query Atlas lineage for "test://health/target-1" with direction "INPUT"
    Then the lineage includes "test://health/source-1"
