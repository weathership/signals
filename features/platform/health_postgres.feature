@platform @health @postgres
Feature: PostgreSQL health

  @tier-0
  Scenario: PostgreSQL accepts connections with required extensions
    When I connect to the "signals" database
    Then the connection succeeds
    And extension "age" is loaded
    And extension "pg_cron" is loaded
    And extension "pg_trgm" is loaded

  @tier-0
  Scenario: Required databases exist
    When I list PostgreSQL databases
    Then database "signals" exists
    And database "signals_catalog" exists

  @tier-0
  Scenario: Catalog registry schema is initialized
    When I connect to the "signals_catalog" database
    Then table "catalog_databases" exists
    And table "catalog_tables" exists
