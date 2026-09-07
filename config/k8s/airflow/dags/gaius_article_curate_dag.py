"""gaius_article_curate — gaius's daily article curation as a scheduled Coordination Activity.

The first workload migrated onto the Airflow-ordered path (user, 2026-09-07:
"sync via Signals to Airflow has been a pending session objective for most of
the last week"). The run IS the activity:

  declare  → this run declares itself to the Signals engine (control HTTP,
             Signals-internal) with the workload's YuniKorn queue configuration
             as its claim: extract floor 1 while the curation runs. Signals
             asserts that into its queue-share arbiter (judged against the
             physical GPUs) and hands back the lease.
  hold     → deferrable SignalsActivitySensor observing the lease. The gaius
             ENGINE sees its own `article_curate` activity in force on
             Scheduler/WatchActivities, runs the curation, heartbeats, releases
             on completion. No heartbeat for the lease TTL → lapsed → EXPIRED.
  close    → emits Assets zndx.coord.activity.ended and
             zndx.coord.article_curate.ended — the publish slots can schedule
             on the latter once they migrate.

Cadence mirrors gaius's pg_cron `article-curate` / `task.article_curate`
(config/supervision/gaius.textproto: cron "7 9 * * *", net 14400 s). Horizon
7200 s = the curation's own outer bound; the sensor's timeout is horizon + 1 h.
start_date is the migration day so no back-interval run is created at deploy.
"""

from __future__ import annotations

from datetime import datetime

from coord_signals import make_workload_dag

gaius_article_curate = make_workload_dag(
    "gaius_article_curate",
    kind="article_curate",
    peer="gaius",
    claims=[{"leaf": "root.internal.inference.extract", "gpu": 1}],
    horizon_s=7200,
    schedule="7 9 * * *",  # UTC — gaius pg_cron article-curate cadence
    reason="daily article curation (Brave + arXiv) — extract floor 1 while it runs",
    tags=["coordination", "workload", "gaius"],
    description="gaius daily article curation as a Coordination Activity (extract floor 1 while it runs)",
    start_date=datetime(2026, 9, 7),
    catchup=False,
)
