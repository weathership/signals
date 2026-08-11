"""Signals lab smoke DAG — proves Airflow 3 scheduler + dag-processor path.

Not a Metaflow-generated DAG; M2 gate only. Metaflow `airflow create` DAGs
land in the same ConfigMap / dags volume in a later step.
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


def _smoke_probe(**_context) -> str:
    msg = "signals-airflow-smoke: ok"
    print(msg)
    return msg


with DAG(
    dag_id="signals_smoke",
    description="Platform Airflow M2 smoke (LocalExecutor)",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["signals", "smoke", "platform"],
    max_active_runs=1,
) as dag:
    start = EmptyOperator(task_id="start")
    probe = PythonOperator(
        task_id="smoke_probe",
        python_callable=_smoke_probe,
    )
    done = EmptyOperator(task_id="done")
    start >> probe >> done
