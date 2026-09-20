# Theta historical weeks: Airflow backfill (2026-09-20)

`just theta-backfill` creates an Airflow 3 backfill for `gaius_theta_cycle`
(`POST /api/v2/backfills`, `max_active_runs=1`). DAG catchup stays false.
Each Monday run stamps `zndx.logical_date` so Gaius consolidates that week's
closed ISO slice.

Canonical: `gaius/docs/scratch/2026-09-20/150500_theta_airflow_backfill.md`
