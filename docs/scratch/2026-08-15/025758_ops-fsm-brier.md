# K8s ops FSM + Brier ledger

`src/signals/ops/`: ProcedureFSM, ObservationLedger (synth-shaped,
state-keyed Brier), `k8s.product-redeploy` as first **method**.

`just redeploy` → `uv run python -m signals.ops redeploy`.

Ill-posed claims (terminal asserted from a holding state) resolve false.
ACP surface: `python -m signals.ops methods|method|risk|report`.
