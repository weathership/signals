# Theta miss is a persistent failure (Signals spec, 2026-09-20)

`dag.gaius_theta_cycle` is now a cadenced Airflow DAG on the Signals Nautilus
instance: Monday 06:00, `CHANNEL_AGENDA_EVENT` at horizon slot 3. A miss or
not-caught-up previous ISO week is a failure until a successful tick. Do not
catch up as a job. Do not treat Gaius MISSTICK as Airflow down.

Canonical write-up: `gaius/docs/scratch/2026-09-20/144110_theta_miss_is_persistent_failure.md`
