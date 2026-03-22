@analytics @otel
Feature: OTel root cause analysis
  As an OTel analyst performing RCA,
  I want to correlate degradation signals with infrastructure changes,
  so that I can generate evidence-backed root cause reports.

  @tier-3 @engine-required @viz-required
  Scenario: Correlate degradation with telemetry signals
    Given the agent has access to OTel telemetry data
    When I identify an observed performance degradation
    Then the agent correlates it with infrastructure change events
    And presents a timeline of contributing factors

  @tier-3 @engine-required @viz-required
  Scenario: Compose multi-system RCA view
    Given correlated signals from multiple systems
    When I request a root cause analysis view
    Then the agent composes a multi-system visualization
    And evidence of correlation is captured in the report
