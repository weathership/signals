"""Signals lab CI DAG — proves Airflow 3 scheduler + dag-processor path.

Elevated platform gate (not a one-off smoke script). Metaflow `airflow create`
DAGs land in the same ConfigMap / dags volume in a later step.

Legacy dual-map: CloudEvent type `dev.signals.smoke.trigger` still routes here.
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


def _ci_probe(**_context) -> str:
    msg = "signals-airflow-ci: ok"
    print(msg)
    return msg


with DAG(
    dag_id="signals_ci",
    description="Platform Airflow M2 CI gate (LocalExecutor)",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["signals", "ci", "platform"],
    max_active_runs=1,
) as dag:
    start = EmptyOperator(task_id="start")
    probe = PythonOperator(
        task_id="ci_probe",
        python_callable=_ci_probe,
    )
    done = EmptyOperator(task_id="done")
    start >> probe >> done
