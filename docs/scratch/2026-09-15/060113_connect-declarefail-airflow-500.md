# Connect 502 DECLAREFAIL — Airflow api-server poisoned session

Hermes Listen Connect returned

```
#HS.COORD.00000001.DECLAREFAIL DeclareActivity at Signals engine
127.0.0.1:50551 failed: StatusCode.UNAVAILABLE
#AF.00000004.APIERROR Airflow API GET /api/v2/dags/coord_interactive_session
→ HTTP 500
```

Not WebRTC. `WebRtcOffer` declares an Activity; Signals `_ensure_dag`
GETs that DAG; Airflow 3.1.7 api-server answered 500 for every
authenticated `/api/v2/dags*` (health stayed 200).

Root: `sqlalchemy.exc.PendingRollbackError` on the FAB auth
`deserialize_user` session. First 500s in the current log start
02:17 UTC (`GET …/gaius_fmp_roll/dagRuns/scheduled__2026-09-15T02:07:00+00:00`).
WatchActivities (hermes + gaius) retried that GET every ~30 s and kept
the session poisoned.

Ops: `kubectl -n airflow rollout restart deploy/airflow-api-server`
(05:51 UTC). After Ready:

- `GET /api/v2/dags/coord_interactive_session` → 200, unpaused
- `agent_rtc` pool open_slots=1
- `DeclareActivity` (interactive, skip List) → accepted in 0.29 s,
  released

`ListActivities(active_only=True)` still walked every historical
schedule-declared lease (551 files) as sequential `GET /dagRuns` and
hit the peer 15 s deadline. Connect swallows that in
`release_stale_interactive` then declares; the 15 s delay is gone once
`list(active_only=True)` uses `_records(recent_only=True)` (in-force
leases have no `ended_ns`).
