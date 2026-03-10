@agent @evolution
Feature: Agent self-improvement
  As an evaluation developer,
  I want to define performance objectives with discrete outcomes,
  so that the agent can engage in self-improvement cycles.

  @tier-2 @engine-required
  Scenario: Define performance objective
    Given I specify a quantitative performance target
    When the agent receives the objective
    Then it establishes a baseline measurement
    And begins an improvement iteration

  @tier-2 @engine-required
  Scenario: Agent completes improvement cycle
    Given the agent is running an improvement iteration
    When the iteration completes
    Then quantitative results are recorded
    And the agent reports whether the target was met

  @tier-2 @engine-required
  Scenario: Export enhanced workflow template
    Given an improvement cycle has succeeded
    When I request the enhanced workflow
    Then a workflow template is generated
    And the template is available for download and redeployment
