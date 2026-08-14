# Landing: Atelier layout + engine GetDashboard

**Date:** 2026-08-13

## Done

### Chrome
- Top nav: Applications · Queues · Lineage (Status removed)
- `/status` → `307 /#scheduler`

### Protocol / engine
- `zndx.yunikorn.v1.GetDashboard` — fan-in clusters, partitions, history apps/containers, node utilizations
- Servicer builds cluster strip + status slices + history + util buckets
- Private YK REST only inside engine

### UI
- Atelier-shaped `/`: hero, health/partition/apps/containers stats, product cards
- Below-fold **Scheduler** band: cluster strip, donuts, area histories, node util bars
- Data: `GET /api/engine/v1/dashboard` → engine gRPC only
- JS: `assets/js/landing-dashboard.js` (SVG Kumo-ish charts)

### Verify
```
curl /api/engine/v1/dashboard  → healthy, 7 apps, 1440 hist pts, 4 util series
browser landing strip: NAME kubernetes STATUS Active NODES 1 …
nav: Applications Queues Lineage
just ui-test → 6/6
```
