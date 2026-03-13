@platform @data-lifecycle
Feature: Kudu/Iceberg data lifecycle
  As a platform operator,
  I want data to land in Kudu (hot tier), gradually cool, and
  consolidate into Iceberg (warm tier), with Impala queries
  spanning both tiers seamlessly.

  Background:
    Given the catalog stack is running
    And database "lifecycle_test" exists

  @tier-1 @ci
  Scenario: Kudu table accepts inserts and upserts
    Given Kudu table "lifecycle_test.events" with schema:
      | column     | type      | key |
      | event_id   | BIGINT    | yes |
      | ts         | TIMESTAMP | no  |
      | partition  | INT       | no  |
      | payload    | STRING    | no  |
    When I insert 1000 rows into "lifecycle_test.events" across 10 partitions
    And I upsert 200 rows targeting partitions 0-1
    Then "lifecycle_test.events" contains 1000 rows
    And partitions 0-1 have updated payload values

  @tier-1 @ci
  Scenario: Cold partitions consolidate from Kudu to Iceberg via CTAS
    Given Kudu table "lifecycle_test.events" has data across 10 partitions
    And partitions 8-9 have had no upserts
    When I consolidate partitions 8-9 into Iceberg table "lifecycle_test.events_archive":
      """
      CREATE TABLE lifecycle_test.events_archive
      STORED AS ICEBERG
      TBLPROPERTIES('iceberg.catalog'='polaris')
      AS SELECT * FROM lifecycle_test.events
      WHERE partition IN (8, 9)
      """
    And I delete consolidated rows from Kudu:
      """
      DELETE FROM lifecycle_test.events WHERE partition IN (8, 9)
      """
    Then "lifecycle_test.events" contains 800 rows
    And "lifecycle_test.events_archive" contains 200 rows

  @tier-1 @ci
  Scenario: Queries span Kudu and Iceberg seamlessly
    Given Kudu table "lifecycle_test.events" has 800 rows in partitions 0-7
    And Iceberg table "lifecycle_test.events_archive" has 200 rows in partitions 8-9
    When I query across both tiers:
      """
      SELECT COUNT(*) AS total FROM (
        SELECT event_id, ts, partition, payload
          FROM lifecycle_test.events
        UNION ALL
        SELECT event_id, ts, partition, payload
          FROM lifecycle_test.events_archive
      ) combined
      """
    Then the result is 1000
    When I query with a predicate spanning both tiers:
      """
      SELECT partition, COUNT(*) AS cnt FROM (
        SELECT partition FROM lifecycle_test.events
        UNION ALL
        SELECT partition FROM lifecycle_test.events_archive
      ) combined
      GROUP BY partition
      ORDER BY partition
      """
    Then every partition 0-9 has exactly 100 rows

  @tier-1 @ci
  Scenario: Ongoing upserts on hot partitions do not affect archived data
    Given the lifecycle workload is in steady state
    When I upsert 500 rows targeting partitions 0-3
    Then "lifecycle_test.events" row count reflects the upserts
    And "lifecycle_test.events_archive" still contains exactly 200 rows
    And a UNION ALL query returns consistent results

  @tier-1 @ci
  Scenario: Schema evolution is consistent across tiers
    Given the lifecycle workload is in steady state
    When I add column "priority" INT to "lifecycle_test.events"
    And I add column "priority" INT to "lifecycle_test.events_archive"
    And I insert rows with the new column into "lifecycle_test.events"
    Then a UNION ALL query includes the new column
    And rows without "priority" return NULL for that column
