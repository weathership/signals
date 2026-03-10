@agent @viz
Feature: Agent-mediated visualization
  As a user interacting through the web terminal,
  I want the agent to direct HoloViews/Datashader/Dask visualizations,
  so that I can explore data interactively with resolution autoscaling.

  Background:
    Given the gRPC engine is running
    And the visualization stack is available

  @tier-2 @engine-required
  Scenario: User issues command via WASM terminal
    Given I am connected to the web terminal
    When I submit an instruction to the agent
    Then the instruction is delivered to the engine via gRPC
    And the agent acknowledges the request

  @tier-3 @viz-required
  Scenario: Agent recomputes visualization on interaction
    Given the agent has an active HoloViews session
    When I interact with a visualization component
    Then Dask recomputes the view in parallel
    And Datashader rasterizes the updated result
    And the updated visualization streams to the web client

  @tier-3 @viz-required
  Scenario: Resolution autoscaling on zoom
    Given a Datashader-rendered view is displayed
    When I change the zoom level
    Then the view recomputes at the new resolution
    And detail increases as the viewport narrows

  @tier-3 @viz-required
  Scenario Outline: Persona-appropriate view
    Given the agent has loaded a dataset
    When I select the "<persona>" persona
    Then the visualization adapts to "<persona>" conventions
    And relevant metrics are foregrounded

    Examples:
      | persona              |
      | Data Scientist       |
      | Domain Researcher    |
      | Quantitative Analyst |
      | Operational Analyst  |
      | Business Analyst     |
