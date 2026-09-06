"""coord_activity — a Coordination Activity: inter-project intent with a lifetime.

One run = one Activity (or one renewal of it). The Signals engine is the only
party that triggers, renews and releases these runs
(``zndx.scheduler.v1.Scheduler`` Declare/Renew/Release/List/WatchActivities);
peer engines never call Airflow. The run's ``conf`` is the declaration
(activity_id, kind, peer, owner, claims, precludes, postures, horizon_*); the
run STATE is the truth every peer reads:

  running                          → intent in force
  success + note "released by …"   → RELEASED (owner released before the horizon)
  success + note "renewed → …"     → SUPERSEDED (a later run carries the id)
  success, no note                 → EXPIRED (the hold reached horizon_iso)
  failed                           → FAILED (intent NOT in force)

Tasks: ``declare`` (log the declaration; emits the ``zndx.coord.activity``
Asset so other DAGs can schedule on activity starts) → ``hold`` (deferrable
sensor until ``horizon_iso`` — no worker slot while waiting) → ``expire``
(logs that the horizon passed without release or renewal).

Spec: signals-protocol specification/protocol/coordination_activities.md
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.standard.sensors.date_time import DateTimeSensorAsync
from airflow.sdk import Asset

default_args = {
    "owner": "signals",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
}

ACTIVITY_ASSET = Asset("zndx.coord.activity")


def _declare(**context) -> str:
    conf = dict(context["dag_run"].conf or {})
    line = json.dumps(conf, sort_keys=True, default=str)
    print(f"coord_activity declare: {line}")
    return conf.get("activity_id", "")


def _expire(**context) -> str:
    conf = dict(context["dag_run"].conf or {})
    msg = (
        f"coord_activity expire: activity {conf.get('activity_id')} kind={conf.get('kind')} "
        f"peer={conf.get('peer')} reached horizon {conf.get('horizon_iso')} without release or renewal"
    )
    print(msg)
    return msg


with DAG(
    dag_id="coord_activity",
    description="Coordination Activity: inter-project intent with a lifetime (Signals-owned)",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    is_paused_upon_creation=False,
    tags=["coordination", "federation", "signals"],
    max_active_runs=32,
) as dag:
    declare = PythonOperator(
        task_id="declare",
        python_callable=_declare,
        outlets=[ACTIVITY_ASSET],
    )
    hold = DateTimeSensorAsync(
        task_id="hold",
        target_time="{{ dag_run.conf['horizon_iso'] }}",
    )
    expire = PythonOperator(
        task_id="expire",
        python_callable=_expire,
    )
    declare >> hold >> expire
