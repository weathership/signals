@classification @dst @evidence
Feature: Dempster-Shafer evidence fusion
  As the classification pipeline,
  I need to combine independent evidence sources
  via Dempster's rule of combination
  so that uncertainty is honestly represented as belief intervals.

  @tier-0
  Scenario: Cosine similarities convert to a valid mass function
    Given the SIGDG frame of discernment
    And cosine similarities across leaf categories
    When I convert cosine similarities to a mass function with discount 0.3
    Then the mass function is valid
    And the Theta focal element has mass approximately 0.3

  @tier-0
  Scenario: Pattern signals produce targeted mass
    Given the SIGDG frame of discernment
    When I convert pattern signals ["email_pattern"] to a mass function
    Then the mass function is valid
    And the EmailAddress singleton has the highest mass

  @tier-0
  Scenario: Name match produces mass for matching categories
    Given the SIGDG frame of discernment and category set
    When I evaluate name match for column "email_address"
    Then the mass function is valid
    And the EmailAddress singleton has non-zero mass

  @tier-0
  Scenario: Dempster combination of two sources
    Given two independent mass functions over the SIGDG frame
    When I combine them using Dempster's rule
    Then the combined assignment is valid
    And the conflict K is between 0 and 1
    And belief <= plausibility for every singleton

  @tier-0
  Scenario: Combining multiple sources via combine_multiple
    Given mass functions from cosine, pattern, and name-match sources
    When I combine all three using combine_multiple
    Then the combined assignment is valid

  @tier-0
  Scenario: Confusable pairs receive redistributed mass
    Given the SIGDG frame with confusable pairs
    Then the frame has at least one confusable pair focal element

  @tier-0
  Scenario: Vacuous mass function represents total ignorance
    Given the SIGDG frame of discernment
    When I create a vacuous mass function
    Then all mass is on Theta
    And belief for any singleton is 0
