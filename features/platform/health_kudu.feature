@platform @health @kudu
Feature: Kudu health

  @tier-0
  Scenario: Kudu master web UI is reachable
    When I request the Kudu master status page
    Then the response status is 200

  @tier-0
  Scenario: Kudu tablet server is registered
    When I request the Kudu master tablet servers list
    Then at least 1 tablet server is registered

  @tier-0
  Scenario: Kudu accepts table operations via Impala
    When I create a Kudu test table "health_check.ping" via Impala
    And I insert a row into "health_check.ping"
    And I select from "health_check.ping"
    Then the result contains the inserted row
    And I drop table "health_check.ping"
