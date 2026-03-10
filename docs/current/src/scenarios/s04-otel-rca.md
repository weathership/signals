# S04: OTel Root Cause Analysis

> Feature Set A — `features/analytics/otel_investigation.feature`

## Intent

An OTel analyst performing RCA correlates observed degradation with telemetry signals and infrastructure changes, engaging the agent to capture evidence of correlation and compose multi-system views.

## Scenarios

### Correlate degradation with telemetry signals
**Tier 3** `@engine-required` `@viz-required`

Given access to OTel telemetry data, the analyst identifies an observed performance degradation. The agent correlates it with infrastructure change events and presents a timeline of contributing factors.

### Compose multi-system RCA view
**Tier 3** `@engine-required` `@viz-required`

Given correlated signals from multiple systems, the analyst requests a root cause analysis view. The agent composes a multi-system visualization with evidence of correlation captured in the report.

## Draft Scenario Mapping

From the draft overview (Scenario 04):

- OTel analyst performing RCA report generation → Both scenarios
- Correlate observed degradation with telemetry signals with infrastructure changes → **Correlate degradation with telemetry signals**
- Engage agent to capture evidence of correlation and likely root cause → **Compose multi-system RCA view**
- Compose multi-system views → **Compose multi-system RCA view**
