"""FSM-tagged probes. Ill-posed claims resolve false (Brier demerit)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from signals.ops.fsm import ProcedureFSM
from signals.ops.ledger import ObservationLedger
from signals.ops.procedures import PROBE_WELL_POSED


def claim(
    ledger: ObservationLedger,
    fsm: ProcedureFSM,
    observer: str,
    proposition: str,
    observe: Callable[[], tuple[bool, str]],
    *,
    p: float | None = None,
    implicit_fsm: str = "",
    implicit_state: str = "",
) -> tuple[bool, str]:
    """Forecast ``proposition`` from ``fsm.current``.

    If this observer is not well-posed here, record ``ill_posed`` and
    resolve false immediately — that is the demerit for an FSM-aware
    claim made from the wrong position. ``implicit_*`` tags the object
    machine (YK Application, Deploy, Pod, Job) at claim time.
    """
    allowed = PROBE_WELL_POSED.get(observer, frozenset({fsm.current}))
    if not fsm.well_posed(allowed):
        oid = ledger.record(
            observer,
            proposition,
            "ill_posed",
            f"claimed from {fsm.current} (allowed {sorted(allowed)})",
            procedure=fsm.name,
            fsm_state=fsm.current,
            implicit_fsm=implicit_fsm,
            implicit_state=implicit_state or "ill-posed",
            p=p,
        )
        ledger.resolve(oid, False, "ill-posed")
        return False, f"ill-posed from {fsm.current}"

    truth, evidence = observe()
    verdict = "satisfied" if truth else "unverified"
    oid = ledger.record(
        observer,
        proposition,
        verdict,
        evidence,
        procedure=fsm.name,
        fsm_state=fsm.current,
        implicit_fsm=implicit_fsm,
        implicit_state=implicit_state,
        p=p,
    )
    ledger.resolve(oid, truth, "oracle")
    return truth, evidence


def risk_line(ledger: ObservationLedger, fsm: ProcedureFSM, observer: str) -> str:
    r = ledger.forecast_risk(observer, fsm.current, procedure=fsm.name)
    return (
        f"{observer} @{fsm.current} risk={r['risk']:.2f} "
        f"n={r['n']} {r['note']}"
    )


def method_forecasts(ledger: ObservationLedger, fsm: ProcedureFSM) -> list[dict[str, Any]]:
    """Per-probe risk at the current FSM position (ACP preflight)."""
    rows = []
    for observer, allowed in PROBE_WELL_POSED.items():
        if fsm.current in allowed:
            rows.append(ledger.forecast_risk(observer, fsm.current, procedure=fsm.name))
    return rows
