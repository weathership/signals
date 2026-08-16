# IT-ops FSM and Brier ledger

IT operations are **methods**: a named FSM, not a pile of kubectl lines. Each
probe is a **forecast** (proposition + implied *p*) tagged with the FSM state
it was made from. When the oracle (kubectl / YuniKorn GET) resolves the claim,
we score **Brier** per `(observer, method fsm_state, implicit object FSM +
state, procedure, epoch)`. The method cell is where *we* were; the implicit
cell is the K8s/YK object machine (`yk.application=running` vs `completing`,
`k8s.deploy=desired_positive`, `k8s.job=active`). Mixing those hid the
Helm-Job miss (method said `apps_completing`, object was still `Running`).

This is the same discipline as synth’s Deluge calibration ledger and cyberphy
converge (fail loud, do not treat a holding state as done). Signals holds the
K8s-first catalog so ACP agents can run a **method** with a risk number, not a
vibe.

## Law

1. **Holding is not terminal.** YK `Completing` still owns the `app-id`.
   Deployment `spec.replicas` still 1 still owns the ReplicaSet.
2. **Ill-posed claims resolve false.** Asserting `yk-apps-completed` from
   `start` or `scaling` is a demerit even if a GET happens to look empty.
3. **Uncalibrated is 0.5 risk**, not 0. No track record → honest ignorance.
4. **Timeout fails the procedure.** It does not WARN-and-apply.

## First method: `k8s.product-redeploy`

`just redeploy` / `uv run python -m signals.ops redeploy`

```text
start → substrate_ready → scaling → desired_zero
      → pods_draining? → pods_quiet
      → apps_completing? → apps_completed
      → applying → verifying → placed
                 ↘ failed (from any non-terminal)
```

Holding: `scaling`, `desired_zero`, `pods_draining`, `apps_completing`.

## `data-product.tier-upkeep`

Weekly **ADD** next 168-hour Kudu range, then settle weeks ≥ 4 weeks old
(copy → verify → **DROP RANGE PARTITION**). Holding through `dropping`.
Do not DROP from `verifying`.

Metaflow flow: `signals.flows.tier_upkeep.DataProductTierUpkeep`.
Airflow is the clock. YK: flow-level proxy sentinel
`signals-dataproduct-tier-upkeep` on `root.platform`
(`config/platform/tier-upkeep-sentinel.yaml`). A `@kubernetes` step **is**
an Application — reuse that app-id.

```bash
just tier-upkeep
uv run python -m signals.ops method data-product.tier-upkeep
```

## Agent / ACP surface

No extra flags. The method is the command.

| Command | Role |
|---------|------|
| `python -m signals.ops methods` | List registered methods |
| `python -m signals.ops method [name]` | JSON method (states, holding, well-posed probes) |
| `python -m signals.ops risk --state apps_completing` | Forecast risk for well-posed probes here |
| `python -m signals.ops report [--axis method\|implicit\|both]` | Ledger Brier table |
| `python -m signals.ops redeploy` | Walk `k8s.product-redeploy` against the live cluster |
| `python -m signals.ops review-product <id>` | Record History event + ACP brief (quality, lineage, delta) |
| `python -m signals.ops record-snapshot --flow F --run-id R` | First product: map a Metaflow run + ACP upkeep assessment onto `details` |

An ACP agent should: list `methods`, load a `method`, refuse transitions the
graph does not allow, consult `risk` before acting, and never treat a holding
state as `placed`.

Ledger file: `build/state/ops-observations.jsonl` (gitignored).

## Lineage

| Piece | Where |
|-------|--------|
| Brier + α shrink | synth `engine/calibration.py` (Signals DST discount is the parent) |
| Converge / fail loud | cyberphy `zarf/converge` CLOSURE |
| This walk | `src/signals/ops/` |
