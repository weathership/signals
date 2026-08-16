# Implicit K8s/YK FSM on the Brier ledger

Each claim now records `implicit_fsm` + `implicit_state` (object machine)
beside the method `fsm_state`. Fleet reduction: Running beats Completing
on `yk.application` so a Helm Job leak does not share a cell with a
true Completing wait.

```
uv run python -m signals.ops report --axis implicit
uv run python -m signals.ops report --axis both
```
