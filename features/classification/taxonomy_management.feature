@classification @taxonomy
Feature: Taxonomy management
  As a pipeline operator,
  I need to work with different taxonomies (SIGDG, annotations, custom)
  so that the classifier can adapt to any organizational vocabulary.

  @tier-0
  Scenario: Build SIGDG flat category set
    When I build the SIGDG category set with hierarchical = false
    Then it contains 30 leaf categories
    And each category has a code, label, and embedding_text
    And the category set name is "sigdg"

  @tier-0
  Scenario: Build SIGDG hierarchical category set
    When I build the SIGDG category set with hierarchical = true
    Then it contains 30 leaf categories in the leaves
    And all_categories includes parent nodes
    And leaf_codes returns a frozenset of 30 codes

  @tier-0
  Scenario: Hierarchical navigation works
    Given the SIGDG hierarchical category set is loaded
    Then descendants of a parent code include its leaf children
    And ancestors of a leaf code return the path to root

  @tier-0
  Scenario: Category set supports code and abbreviation lookup
    Given the SIGDG category set is loaded
    When I look up code "0076"
    Then the category label is "EmailAddress"
    When I look up abbreviation "EMAIL"
    Then the resolved category has code "0076"
