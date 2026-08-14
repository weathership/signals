# zndx.scheduler.v1 — proto review before submodule lock-in

**Date:** 2026-08-14

## Decision

Do **not** lock `zndx.yunikorn.v1`. YuniKorn is a backend. Public face is
`zndx.scheduler.v1.Scheduler`. Unpublished yunikorn package removed.

## Shape

| | |
|--|--|
| Package / service | `zndx.scheduler.v1` / `Scheduler` |
| Engine Status | `capability=scheduler`, `model=yunikorn` (lab) |
| Policy | `PolicyDocument{media_type, body}` not `yaml` |
| Work units | application (job) + task (allocation) |
| Domain | `partition` (YK / SLURM / PBS-mapped) |
| Dashboard | `SchedulerSummary` + `task_*` not `container_*` |
| Placement | `GetPlacementPolicy` |

Lab YuniKorn mapping lives in spec appendix + engine `yk_client.py` only.

## Verified live

```
grpcurl list → zndx.engine.v1.Engine + zndx.scheduler.v1.Scheduler
Status capability=scheduler model=yunikorn
signals-yk health → healthy backend=yunikorn
GET /api/engine/v1/dashboard → backend yunikorn, 7 apps, 23 tasks
tests/signals → 16 passed
```
