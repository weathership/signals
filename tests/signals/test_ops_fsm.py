"""Procedure FSM + ill-posed Brier demerits."""

from __future__ import annotations

from pathlib import Path

import pytest

from signals.ops.fsm import IllegalTransition
from signals.ops.ledger import ObservationLedger
from signals.ops.probes import claim
from signals.ops.procedures import (
    DATA_PRODUCT_TIER_UPKEEP,
    get_method,
    k8s_product_redeploy,
)


def test_illegal_skip_holding() -> None:
    fsm = k8s_product_redeploy()
    fsm.step("substrate_ready")
    fsm.step("scaling")
    with pytest.raises(IllegalTransition):
        fsm.step("apps_completed")


def test_completing_is_holding() -> None:
    fsm = k8s_product_redeploy()
    for s in (
        "substrate_ready",
        "scaling",
        "desired_zero",
        "pods_quiet",
        "apps_completing",
    ):
        fsm.step(s)
    assert fsm.is_holding()
    assert not fsm.is_terminal()


def test_ill_posed_claim_demerit(tmp_path: Path) -> None:
    fsm = k8s_product_redeploy()
    led = ObservationLedger(tmp_path / "obs.jsonl", engine_rev="test")
    # From start, claiming yk-completed is ill-posed.
    ok, ev = claim(
        led,
        fsm,
        "probe:yk-completed",
        "yk-apps-completed",
        lambda: (True, "should not be trusted"),
    )
    assert ok is False
    assert "ill-posed" in ev
    brier, n = led.score("probe:yk-completed", "start", procedure=fsm.name)
    assert n == 1
    assert brier is not None and brier > 0.5


def test_well_posed_true_low_brier(tmp_path: Path) -> None:
    fsm = k8s_product_redeploy()
    for s in ("substrate_ready", "scaling"):
        fsm.step(s)
    led = ObservationLedger(tmp_path / "obs.jsonl", engine_rev="test")
    ok, _ = claim(
        led,
        fsm,
        "probe:desired-zero",
        "desired-zero",
        lambda: (True, "desired=0"),
    )
    assert ok is True
    brier, n = led.score("probe:desired-zero", "scaling", procedure=fsm.name)
    assert n == 1
    assert brier is not None and brier < 0.1


def test_tier_upkeep_holds_until_drop() -> None:
    fsm = get_method(DATA_PRODUCT_TIER_UPKEEP)
    fsm.step("adding")
    fsm.step("copying")
    fsm.step("verifying")
    assert fsm.is_holding()
    with pytest.raises(IllegalTransition):
        fsm.step("settled")
    fsm.step("dropping")
    assert fsm.is_holding()
    fsm.step("settled")
    assert fsm.is_terminal()


def test_uncalibrated_risk_is_half(tmp_path: Path) -> None:
    led = ObservationLedger(tmp_path / "obs.jsonl", engine_rev="test")
    r = led.forecast_risk("probe:pods-quiet", "pods_draining", procedure="k8s.product-redeploy")
    assert r["n"] == 0
    assert r["risk"] == 0.5
    assert "uncalibrated" in r["note"]


def test_method_lists_holding() -> None:
    from signals.ops.procedures import describe_method, get_method

    doc = describe_method(get_method("k8s.product-redeploy"))
    assert "apps_completing" in doc["holding"]
    assert "placed" in doc["terminals"]
    assert doc["name"] == "k8s.product-redeploy"
    assert "probe:yk-completed" in doc["probes"]
    assert "yk.application" in doc["implicit"]
    assert "completing" in doc["implicit"]["yk.application"]["holding"]


def test_unknown_method() -> None:
    from signals.ops.procedures import get_method

    with pytest.raises(KeyError, match="unknown method"):
        get_method("k8s.scorched-earth")


def test_yk_implicit_reduce_running_beats_completing() -> None:
    from signals.ops.implicit import YK_APPLICATION

    assert YK_APPLICATION.reduce(["completing", "running", "completed"]) == "running"
    assert YK_APPLICATION.reduce(["completing", "completed"]) == "completing"
    assert YK_APPLICATION.reduce(["completed", "missing"]) == "completed"
    assert YK_APPLICATION.is_holding("completing")
    assert not YK_APPLICATION.is_holding("completed")


def test_brier_splits_on_implicit_state(tmp_path: Path) -> None:
    fsm = k8s_product_redeploy()
    for s in ("substrate_ready", "scaling", "desired_zero", "pods_quiet"):
        fsm.step(s)
    led = ObservationLedger(tmp_path / "obs.jsonl", engine_rev="test")
    # Same method cell, two implicit YK cells.
    claim(
        led,
        fsm,
        "probe:yk-completed",
        "yk-apps-completed",
        lambda: (False, "still running"),
        implicit_fsm="yk.application",
        implicit_state="running",
    )
    fsm.step("apps_completing")
    claim(
        led,
        fsm,
        "probe:yk-completed",
        "yk-apps-completed",
        lambda: (True, "completing then done"),
        implicit_fsm="yk.application",
        implicit_state="completing",
    )
    b_run, n_run = led.score(
        "probe:yk-completed",
        procedure=fsm.name,
        implicit_fsm="yk.application",
        implicit_state="running",
    )
    b_cmp, n_cmp = led.score(
        "probe:yk-completed",
        procedure=fsm.name,
        implicit_fsm="yk.application",
        implicit_state="completing",
    )
    assert n_run == 1 and n_cmp == 1
    assert b_run is not None and b_cmp is not None
    # unverified+false vs satisfied+true — both calibrated, not mixed.
    both, n_both = led.score("probe:yk-completed", procedure=fsm.name)
    assert n_both == 2
    rows = led.report(axis="implicit")
    cells = {
        (r["implicit_fsm"], r["implicit_state"])
        for r in rows
        if r["observer"] == "probe:yk-completed"
    }
    assert ("yk.application", "running") in cells
    assert ("yk.application", "completing") in cells
