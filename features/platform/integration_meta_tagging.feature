@platform @integration @meta-tagging
Feature: Atlas classifications on Impala tables and columns

  Background:
    Given database "integration_test" exists in Impala

  @tier-1
  Scenario: Create a custom classification in Atlas
    When I create Atlas classification type "PII"
    Then the classification type "PII" exists in Atlas

  @tier-1
  Scenario: Apply classification to an Impala table
    Given Atlas classification type "PII" exists
    And Kudu table "integration_test.tagged_table" is registered in Atlas
    When I apply classification "PII" to Kudu table "integration_test.tagged_table"
    Then the entity has classification "PII"

  @tier-1
  Scenario: Apply classification to a specific column
    Given Atlas classification type "PII" exists
    And column "email" of Kudu table "integration_test.tagged_table" is registered in Atlas
    When I apply classification "PII" to column "email" of "integration_test.tagged_table"
    Then the column entity has classification "PII"

  @tier-1
  Scenario: Search for entities by classification
    Given multiple tables have classification "PII"
    When I search Atlas for entities with classification "PII"
    Then the results include all tagged tables
