@agent @extension
Feature: Algorithm extension lifecycle
  As an algorithm developer,
  I want to package and deploy custom analysis code as platform extensions,
  so that the agent can leverage them in distributed compute contexts.

  @tier-0
  Scenario: Package algorithm as extension
    Given I have developed a Dask-based analysis module
    When I package it as a platform extension
    Then the extension metadata is valid
    And the extension archive is created

  @tier-2 @engine-required
  Scenario: Deploy extension to running platform
    Given a packaged extension is available
    When I deploy the extension to the platform
    Then the agent registers the new capability
    And the extension appears in the capability inventory

  @tier-3 @engine-required @viz-required
  Scenario: Agent invokes extension in compute context
    Given an extension is deployed and registered
    When the agent selects it for an analysis task
    Then the extension executes within the Dask distributed context
    And results are surfaced through HoloViews components
