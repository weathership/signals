# Theta historical weeks: Airflow backfill (2026-09-20)

`just theta-backfill` default is **one UTC day per run** (manual dagRuns with
`conf.window_date`). Each day refines the same ISO-week `theta_consolidation_runs`
row. The product is the week consolidation. `--weekly` is `POST /api/v2/backfills`
(one Monday per week). DAG catchup stays false. `max_active_runs=1`.

Canonical: `gaius/docs/scratch/2026-09-20/150500_theta_airflow_backfill.md`
