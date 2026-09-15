# gaius_prospects_check skip-as-success (category error)

Airflow `gaius_prospects_check` 07:00 UTC 12–15 Sep 2026 is **success**
with note `released by gaius: skipped: SELECT meta.should_run_prospects_check() is false`.

That is not success. The intended effect is the daily check (and an
update when the check says so). Skip means the effect did not occur.

Live SoR (`zndx_gaius.scheduled_tasks`):

- **Every** `source=airflow` `prospects_check` row in the window is
  `status=skipped` / `reason=gate_false`. `LAST_AIRFLOW_TICK_SQL` has
  **no** airflow completed row.
- Real checks ran as `engine-catchup` / `operator` (12 Sep 11:32 and
  18:39, 13 Sep 21:16, 15 Sep 00:48). Catch-up stamps
  `meta.prospects_cron_state.last_run_at`, so the next 07:00 gate is
  false and Airflow skip-succeeds.
- 15 Sep 00:49 catch-up enqueued `prospects_update`; Metaflow 5386
  failed `#EP.00000016.NOTREADY` (thinking vLLM). 07:00 then skipped
  because last_run was 00:49 — the failed update never retried. Not
  Theta (`gaius_theta_cycle` has zero runs).

Fix: workload `close` re-reads the lease owner outcome.
`skipped:` / `failed:` / `error:` / `stalled:` → `#CO.0000000F.NOEFFECT`
(DAG fail). Interactive `close` still uses lease-state `released` only.

Needs `scripts/airflow_dags_deploy.sh` so the ConfigMap plugins roll.
