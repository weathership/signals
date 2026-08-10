# Signals Control Plane UI — plan note

Wrote architecture plan:

`docs/current/src/architecture/signals-control-plane-ui.md`

## Inputs reviewed

- YuniKorn web: `~/local/src/asf/rch-yunikorn-web/` (routes, SchedulerService REST)
- Theme: Atelier Keiretsu + Kumo (dark/light)
- Atlas: OL `/api/v1` + native `LineageREST`
- Sentinels: minifi_sentinels.md (YK + Knative + OTel overwatch)

## Direction

One product UI replaces YK web; Atlas enrichment closes Marquez-native gaps;
sentinel/YK/OTel = uniform process duration/history for federated engines.
