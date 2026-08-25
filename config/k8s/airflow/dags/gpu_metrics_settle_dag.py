"""Hourly gpu_metrics analog → Iceberg verify → Kudu DROP RANGE.

Metaflow is the work (`signals.flows.gpu_metrics_settle`). This DAG is
the Airflow clock. pg_cron on devenv :5455 runs the same honesty path
for hours already analoged (`public.gpu_metrics_settle()`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "signals",
    "depends_on_past": False,
    "email_on_failure": True,
    "retries": 0,
    "retry_delay": timedelta(minutes=5),
}


def _settle(**_context) -> str:
    from signals.ops.gpu_metrics_settle import walk

    doc = walk(apply=True, analog=True)
    return str(doc)


with DAG(
    dag_id="gpu_metrics_settle",
    description="Iceberg verify + Kudu DROP RANGE for closed gpu_metrics hours",
    default_args=default_args,
    schedule="5 * * * *",
    start_date=datetime(2026, 8, 1),
    catchup=False,
    tags=["signals", "warehouse", "gpu-metrics"],
    max_active_runs=1,
) as dag:
    PythonOperator(task_id="settle", python_callable=_settle)
