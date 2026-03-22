@classification @features
Feature: Column feature extraction
  As the classification pipeline,
  I need to extract 12 discrete, ablatable features from column metadata
  so that each feature's contribution can be measured by SAGE.

  @tier-0
  Scenario: Extract features from a column with email values
    Given a column sample "email_address" of type "STRING" with values:
      | value              |
      | alice@example.com  |
      | bob@test.org       |
      | carol@domain.co.uk |
    When I extract features from the sample
    Then the feature pattern_signals includes "email_pattern"
    And cardinality is 3
    And avg_value_length is greater than 10

  @tier-0
  Scenario: Detect UUID pattern
    Given a column sample "identifier" of type "STRING" with values:
      | value                                |
      | 550e8400-e29b-41d4-a716-446655440000 |
      | 6ba7b810-9dad-11d1-80b4-00c04fd430c8 |
      | f47ac10b-58cc-4372-a567-0e02b2c3d479 |
    When I extract features from the sample
    Then the feature pattern_signals includes "uuid_pattern"

  @tier-0
  Scenario: Feature ablation mask controls embedding text
    Given a column sample with extracted features
    When I build embedding text with all features enabled
    Then the embedding text contains the column name
    When I build embedding text with "sample_values" disabled
    Then the embedding text does not contain sample values

  @tier-0
  Scenario: Null ratio calculated from counts
    Given a column sample "status" of type "STRING" with 20 nulls out of 100
    When I extract features from the sample
    Then null_ratio is 0.2

  @tier-0
  Scenario: Sibling context includes other columns from the same table
    Given a column sample "email" with siblings "name", "phone", "address"
    When I extract features with sibling context
    Then the sibling_context contains "name"
    And the sibling_context contains "phone"
    And the sibling_context contains "address"
