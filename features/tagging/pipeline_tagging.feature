@tagging @pipeline
Feature: End-to-end pipeline tagging
  As a data governance engineer,
  I want the full sample -> classify -> tag pipeline
  to work end-to-end against live Impala and Atlas,
  so that classified columns appear as tagged entities in Atlas.

  Background:
    Given database "tagging_test" exists in Impala

  @tier-1
  Scenario: Full pipeline: create table, classify, tag, verify
    Given Kudu table "tagging_test.customer_data" with typed columns:
      | column       | type    |
      | id           | BIGINT  |
      | email        | STRING  |
      | phone_number | STRING  |
      | full_name    | STRING  |
    And the table has representative data inserted
    And the table is registered in Atlas
    When I run the Tagger on "tagging_test.customer_data"
    Then the TagReport shows tables_processed = 1
    And the TagReport shows columns_classified >= 1

  @tier-1
  Scenario: Dry-run pipeline produces report without Atlas writes
    Given Kudu table "tagging_test.dry_run_data" with typed columns:
      | column       | type    |
      | id           | BIGINT  |
      | email        | STRING  |
      | ssn          | STRING  |
    And the table has representative data inserted
    When I run the Tagger in dry-run mode on "tagging_test.dry_run_data"
    Then the TagReport shows tables_processed = 1
    And the TagReport shows columns_tagged = 0
