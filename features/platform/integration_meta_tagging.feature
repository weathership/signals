@platform @integration @meta-tagging
Feature: Atlas classifications on Impala tables and columns

  @tier-1 @tdd
  Scenario: Create a custom classification in Atlas
    When I create Atlas classification type "PII"
    Then the classification type "PII" exists in Atlas

  @tier-1 @tdd
  Scenario: Apply classification to an Impala table
    Given Atlas classification type "PII" exists
    And Kudu table "integration_test.tagged_table" is registered in Atlas
    When I apply classification "PII" to entity "integration_test.tagged_table"
    Then the entity has classification "PII"

  @tier-1 @tdd
  Scenario: Apply classification to a specific column
    Given column "email" of Kudu table "integration_test.tagged_table" is registered in Atlas
    When I apply classification "PII" to column "email" of "integration_test.tagged_table"
    Then the column entity has classification "PII"

  @tier-1 @tdd
  Scenario: Search for entities by classification
    Given multiple tables have classification "PII"
    When I search Atlas for entities with classification "PII"
    Then the results include all tagged tables
