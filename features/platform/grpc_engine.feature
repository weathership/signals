@platform @engine @grpc
Feature: gRPC engine connectivity
  As a client (WASM terminal or test harness),
  I want to connect to the gRPC engine,
  so that I can send instructions and receive responses.

  @tier-2 @engine-required
  Scenario: Engine accepts gRPC connection
    Given the gRPC engine is running
    When I open a gRPC channel to the engine
    Then the channel is established
    And the health check returns SERVING

  @tier-2 @engine-required
  Scenario: Engine echoes an instruction
    Given a gRPC channel is open
    When I send a test instruction
    Then the engine responds with an acknowledgement
    And the response includes a request identifier
