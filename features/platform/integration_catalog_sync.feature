@platform @integration @catalog-sync
Feature: Cross-component catalog synchronization

  Background:
    Given database "integration_test" exists in Impala

  @tier-1
  Scenario: Impala CREATE TABLE registers in Kudu
    When I create Kudu table "integration_test.sync_test" via Impala
    Then the table exists in Kudu master's table list
    And I drop table "integration_test.sync_test"

  @tier-1
  Scenario: Impala CRUD operations work end-to-end on Kudu
    Given Kudu table "integration_test.crud_test" exists
    When I insert 10 rows into "integration_test.crud_test" via Impala
    And I update rows in "integration_test.crud_test" via Impala
    And I delete rows from "integration_test.crud_test" via Impala
    Then "integration_test.crud_test" row count is correct
    And I drop table "integration_test.crud_test"

  @tier-1 @tdd
  Scenario: Atlas discovers Impala-managed Kudu tables
    Given Kudu table "integration_test.atlas_visible" exists
    When I trigger an Atlas metadata import
    Then Atlas entity search finds "integration_test.atlas_visible"
    And I drop table "integration_test.atlas_visible"

  @tier-1 @tdd
  Scenario: Impala DDL events propagate to Atlas
    When I create Kudu table "integration_test.event_test" via Impala
    And I wait for Atlas to process the event
    Then Atlas has an entity for "integration_test.event_test"
    When I drop table "integration_test.event_test" via Impala
    Then the Atlas entity is marked as deleted
