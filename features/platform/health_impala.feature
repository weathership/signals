@platform @health @impala
Feature: Impala health

  @tier-0
  Scenario: Impala accepts SQL queries
    When I connect to Impala via JDBC
    And I run "SELECT 1"
    Then the query result is 1

  @tier-0
  Scenario: Impala catalogd is healthy
    When I request the Impala catalogd web UI
    Then the response status is 200

  @tier-0
  Scenario: Impala can create and query databases
    When I run "CREATE DATABASE IF NOT EXISTS health_check"
    And I run "SHOW DATABASES"
    Then the result contains "health_check"
    When I run "DROP DATABASE health_check"
