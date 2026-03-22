@analytics @cybersec
Feature: Cybersecurity investigation
  As a KQL/SPL cybersecurity analyst,
  I want to investigate malicious behavior using correlated log sources,
  so that I can triage threats and capture representative signals.

  @tier-3 @engine-required @viz-required
  Scenario: Triage with AWS and system logs
    Given the agent has access to AWS logs and system telemetry
    When I describe suspicious network behavior
    Then the agent queries relevant log sources
    And surfaces symptoms and representative signals

  @tier-3 @engine-required @viz-required
  Scenario: Secondary correlative investigation
    Given primary indicators of compromise are identified
    When I request secondary system correlation
    Then the agent correlates with OTel traces and eBPF data
    And historical binary fingerprints are consulted
    And environmental conditions are illustrated

  @tier-3 @engine-required @viz-required
  Scenario: Validate novel detection logic
    Given a proposed detection rule
    When the agent evaluates it against historical data
    Then it confirms whether the rule produces actionable views
    And false positive rates are reported
