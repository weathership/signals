@classification @embedding
Feature: Embedding-based column classification
  As the classification pipeline,
  I want to classify column samples through the EmbeddingClassifier
  which fuses cosine, pattern, and name-match evidence
  into a HierarchicalClassification with belief intervals.

  @tier-0
  Scenario: Classify a column with strong pattern evidence
    Given an EmbeddingClassifier with the SIGDG taxonomy
    When I classify a column "ssn" with values:
      | value       |
      | 123-45-6789 |
      | 987-65-4321 |
      | 111-22-3333 |
    Then the classification is not None
    And the classification has a belief assignment
    And the confidence is above 0

  @tier-0
  Scenario: Classification includes belief interval accessors
    Given a classification result exists on context
    Then belief_at returns a value between 0 and 1
    And plausibility_at >= belief_at for the predicted code
    And uncertainty_gap equals plausibility minus belief

  @tier-0
  Scenario: Classification source masses are recorded
    Given a classification result exists on context
    Then source_masses contains "cosine"
    And source_masses contains "name_match"

  @tier-0
  Scenario: Classification without CatBoost model still works
    Given an EmbeddingClassifier with no model_path
    When I classify a column "email" with values:
      | value             |
      | alice@example.com |
      | bob@test.org      |
    Then the classification is not None
