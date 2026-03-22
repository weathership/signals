@classification @benchmark
Feature: GitTables public benchmark evaluation
  As a data governance engineer evaluating sigint,
  I want to classify the GitTables CTA benchmark dataset
  and measure accuracy against ground truth,
  so that I can assess the pipeline on standardized public data
  before investing in custom taxonomy work.

  Background:
    Given the GitTables taxonomy is loaded with 122 DBpedia types

  @tier-0
  Scenario: Load GitTables benchmark dataset
    Given the GitTables benchmark dataset is available
    Then the dataset contains at least 100 columns
    And each column has a source_table, column_name, and column_type

  @tier-0
  Scenario: Classify GitTables columns with embedding + DST
    Given the GitTables benchmark dataset is available
    And an EmbeddingClassifier is configured for GitTables
    When I classify all GitTables columns
    Then every classification has a belief interval
    And belief <= plausibility for each result

  @tier-0
  Scenario: Evaluate accuracy against ground truth
    Given the GitTables ground truth mapping is available
    And all GitTables columns have been classified
    When I evaluate classifications against the ground truth
    Then accuracy is reported with correct, wrong, and total counts

  @tier-0
  Scenario: Columns with high uncertainty are flagged
    Given all GitTables columns have been classified
    Then at least one classification has uncertainty_gap > 0.3

  @tier-0
  Scenario: SAGE identifies discriminative features
    Given all GitTables columns have been classified
    When I run SAGE analysis with 64 permutations on a subset
    Then SAGE returns importance values for all 12 features
