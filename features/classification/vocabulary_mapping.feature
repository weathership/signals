@classification @vocab
Feature: Vocabulary mapping
  As a pipeline operator with organization-specific terminology,
  I want to map my labels to SIGDG codes
  so that the classifier uses my vocabulary as input.

  @tier-0
  Scenario: Load mapping from JSON file
    Given a vocabulary mapping JSON file with entries:
      | user_label         | code  |
      | Credit Card Number | 0085  |
      | PAN                | 0085  |
      | SSN                | 0083  |
    When I load the VocabMapping from the file
    Then the mapping contains 3 entries

  @tier-0
  Scenario: Exact match resolution
    Given a loaded VocabMapping
    When I resolve "Credit Card Number"
    Then the resolved code is "0085"

  @tier-0
  Scenario: Case-insensitive fallback resolution
    Given a loaded VocabMapping
    When I resolve "credit card number"
    Then the resolved code is "0085"

  @tier-0
  Scenario: Unrecognized label returns None
    Given a loaded VocabMapping
    When I resolve "Unknown Thing"
    Then the resolved code is None
