"""Eventing smoke DAG — proves Knative CE → Airflow path (M3).

Distinct from signals_smoke so event-triggered runs are easy to spot in the UI.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "signals",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
}


def _event_probe(**context) -> str:
    conf = context.get("dag_run").conf if context.get("dag_run") else {}
    msg = f"signals-eventing-smoke: ok conf_keys={sorted((conf or {}).keys())}"
    print(msg)
    print("ce_type=", (conf or {}).get("ce_type"))
    print("ce_source=", (conf or {}).get("ce_source"))
    return msg


with DAG(
    dag_id="signals_eventing_smoke",
    description="Platform M3: Knative Eventing → Airflow DAG run",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["signals", "smoke", "eventing", "platform"],
    max_active_runs=4,
) as dag:
    start = EmptyOperator(task_id="start")
    probe = PythonOperator(task_id="event_probe", python_callable=_event_probe)
    done = EmptyOperator(task_id="done")
    start >> probe >> done
