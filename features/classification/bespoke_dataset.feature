@classification @bespoke
Feature: Transition from benchmark to bespoke metadata dataset
  As a data governance engineer with my own controlled vocabulary,
  I want to move from the public benchmark to a custom taxonomy,
  classify my metadata columns using my vocabulary,
  so that I can apply governance tags specific to my organization.

  This feature captures the primary narrative arc:
  benchmark (GitTables) -> custom taxonomy -> classification -> governance.

  @tier-0
  Scenario: Load a custom taxonomy from an annotations CSV
    Given an annotations CSV with known leaf categories
    When I build a category set from the annotations CSV
    Then the category set has "annotations" as its name
    And the category set contains leaf categories from the CSV
    And each category has embedding text derived from its label

  @tier-0
  Scenario: Custom taxonomy produces a hierarchical category set
    Given an annotations CSV with known leaf categories
    When I build a hierarchical category set from the annotations CSV
    Then the category set has parent-child relationships
    And leaf codes are present in the leaf_codes set

  @tier-0
  Scenario: Classify columns using the custom taxonomy
    Given a hierarchical annotations category set is built
    And an EmbeddingClassifier is configured for the annotations taxonomy
    When I classify a bespoke column "payment_card_number" with values:
      | value            |
      | 4111111111111111 |
      | 5500000000000004 |
      | 340000000000009  |
    Then the bespoke classification result is not None
    And the bespoke classification has a belief assignment

  @tier-0
  Scenario: Config switches between benchmark and bespoke taxonomies
    When I load config with taxonomy_name = "sigdg"
    And I build a category set from the config
    Then the category set name is "sigdg"
    When I load config with taxonomy_name = "annotations" and an annotations path
    And I build a category set from the config
    Then the category set name is "annotations"

  @tier-0
  Scenario: Evidence sources combine correctly for a bespoke taxonomy
    Given a hierarchical annotations category set is built
    And a FrameOfDiscernment is built from the annotations category set
    When I create evidence masses from cosine and name-match sources
    And I combine bespoke evidence using Dempster's rule
    Then the combined bespoke assignment is valid
    And bespoke conflict K is between 0 and 1

  @tier-0
  Scenario: Vocabulary mapping bridges user terms to taxonomy codes
    Given a vocabulary mapping for the bespoke taxonomy
    When I resolve a known user label
    Then the label maps to the expected taxonomy code
    When I resolve an unknown user label
    Then the result is None
