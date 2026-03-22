@classification @config
Feature: Pipeline configuration lifecycle
  As a pipeline operator,
  I want configuration to load from HOCON with env var substitution
  and CLI overrides,
  so that I have a single source of truth with layered precedence.

  @tier-0
  Scenario: Load default configuration from base.conf
    When I load the pipeline config with no overrides
    Then the config has classifier_type = "embedding"
    And the config has confidence_threshold = 0.3
    And the config has taxonomy_name = "sigdg"
    And the config has hierarchical = true

  @tier-0
  Scenario: CLI overrides take precedence over defaults
    When I load the pipeline config with overrides
      | field                | value       |
      | confidence_threshold | 0.5         |
      | taxonomy_name        | annotations |
    Then the config has confidence_threshold = 0.5
    And the config has taxonomy_name = "annotations"

  @tier-0
  Scenario: Materialize config to flat env file
    Given a loaded pipeline config
    When I materialize the config to a temporary path
    Then the materialized file contains "SIGINT_CLASSIFIER_TYPE=embedding"
    And the materialized file contains "SIGINT_TAXONOMY_NAME=sigdg"

  @tier-0
  Scenario: Validate materialized config detects missing conditional keys
    Given a materialized config with classifier_type = "llm" and no API key
    When I validate the materialized config
    Then the validation returns an error mentioning "ANTHROPIC_API_KEY"

  @tier-0
  Scenario: Validate materialized config passes when complete
    Given a fully populated materialized config file
    When I validate the materialized config
    Then the validation returns no errors
