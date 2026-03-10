# S05: Cybersecurity Investigation

> Feature Set A — `features/analytics/cybersec_investigation.feature`

## Intent

A KQL/SPL cybersecurity analyst investigates malicious behavior on their network/systems. They leverage AWS and systems logs alongside existing point solutions to triage threats, capture symptoms and representative signals, and validate novel detection logic.

## Scenarios

### Triage with AWS and system logs
**Tier 3** `@engine-required` `@viz-required`

Given access to AWS logs and system telemetry, the analyst describes suspicious network behavior. The agent queries relevant log sources and surfaces symptoms and representative signals.

### Secondary correlative investigation
**Tier 3** `@engine-required` `@viz-required`

After primary indicators of compromise are identified, the analyst requests secondary system correlation. The agent correlates with OTel traces and eBPF data, consults historical binary fingerprints, and illustrates environmental conditions.

### Validate novel detection logic
**Tier 3** `@engine-required` `@viz-required`

Given a proposed detection rule, the agent evaluates it against historical data. It confirms whether the rule produces actionable views and reports false positive rates.

## Draft Scenario Mapping

From the draft overview (Scenario 05):

- KQL/SPL analyst investigating malicious behavior → All scenarios
- Leverage AWS and systems logs alongside existing point solutions → **Triage with AWS and system logs**
- Provide insight into primary behavior through secondary correlative investigation → **Secondary correlative investigation**
- Illustrate system/environment conditions in support of findings → **Secondary correlative investigation**
- Confirm novel detection logic provides actionable views → **Validate novel detection logic**
