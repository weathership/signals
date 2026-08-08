@platform @lineage @openlineage
Feature: Flink OpenLineage populates Atlas composite SoR (Marquez UI path)
  # Signals SoR: Atlas alone on :21010 — /api/atlas/* (governance) + /api/v1/*
  # (OL ingest + Marquez-compat read). Same signals PG/AGE. No Marquez DB.
  # No Python OL facade. Marquez-web is default stack (devenv up) and proxies /api/v1 → Atlas.
  #
  # M2 landed: Atlas OpenLineageServlet on /api/v1/* (components/atlas).
  # Still @wip: Flink dual-path steps + live producer validation (M3).

  Background:
    Given the Signals stack is ready for lineage tests

  @tier-1 @wip
  Scenario: OpenLineage RunEvent from Flink is accepted by Atlas OL ingest
    When a minimal Flink job emits OpenLineage events to Atlas POST /api/v1/lineage
    Then Atlas GET /api/v1/namespaces lists the job namespace
    And Atlas GET /api/v1 shows at least one run for that job
    And stock Atlas entity APIs remain healthy

  @tier-1 @wip
  Scenario: Marquez-compatible read surface serves the Flink job graph
    Given a Flink job has completed with OpenLineage events in Atlas
    When I query Atlas GET /api/v1/lineage for that job nodeId
    Then the response includes the job and its datasets
    # Marquez-web (always on with devenv up) loads the same Atlas /api/v1 without a Marquez DB

  @tier-1 @wip
  Scenario: Atlas governance clients are unaffected by OL traffic
    When OL events are ingested via Atlas /api/v1/lineage
    Then Atlas admin status is ACTIVE
    And rdbms_table entity CRUD still succeeds for a smoke table
