"""Hourly gpu_metrics analog → Iceberg verify → Kudu DROP RANGE.

Metaflow is the work (`signals.flows.gpu_metrics_settle`). This DAG is
the Airflow clock. Gaius pg_cron on zndx_gaius :5444 is the lab clock
(`scheduled_tasks.gpu_metrics_settle`). Warehouse :5455 is not a clock.
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
