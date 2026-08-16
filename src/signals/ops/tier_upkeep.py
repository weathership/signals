"""data-product.tier-upkeep — ADD next week, settle weeks ≥ 4 weeks old.

Impala SQL is planned here; live apply is the Metaflow flow. YK visibility
is a flow-level proxy sentinel on ``root.platform`` (or a real Application
if a @kubernetes step lands).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from signals.ops.procedures import DATA_PRODUCT_TIER_UPKEEP, get_method
from signals.ops.warehouse import (
    HOURS_PER_WEEK,
    SETTLE_WEEKS,
    TIER0,
    epoch_hour,
    settle_before_hour,
    week_start_hour,
)

TIER0_TABLES = tuple(TIER0.values())
YK_QUEUE = "root.platform"
YK_APP_ID = "signals-dataproduct-tier-upkeep"
SENTINEL_STAMP = Path("config/platform/tier-upkeep-sentinel.yaml")
PROJECT = "signals"


def plan(now_hour: int | None = None) -> dict[str, Any]:
    """Compute ADD / settle hour bounds. No Impala."""
    now = int(now_hour if now_hour is not None else epoch_hour())
    current = week_start_hour(now)
    add_lo = current + HOURS_PER_WEEK
    add_hi = add_lo + HOURS_PER_WEEK
    settle_hi = settle_before_hour(now)
    settle_lo = settle_hi - HOURS_PER_WEEK if settle_hi > 0 else 0
    return {
        "method": DATA_PRODUCT_TIER_UPKEEP,
        "now_hour": now,
        "settle_weeks": SETTLE_WEEKS,
        "yk_queue": YK_QUEUE,
        "yk_app_id": YK_APP_ID,
        "sentinel": str(SENTINEL_STAMP),
        "add": {"lo": add_lo, "hi": add_hi},
        "settle": {"lo": settle_lo, "hi": settle_hi} if settle_hi > 0 else None,
        "tables": list(TIER0_TABLES),
    }


def add_sql(lo: int, hi: int) -> list[str]:
    return [
        f"ALTER TABLE signals_dataproducts.{tbl} "
        f"ADD RANGE PARTITION {lo} <= VALUES < {hi}"
        for tbl in TIER0_TABLES
    ]


def drop_sql(lo: int, hi: int) -> list[str]:
    return [
        f"ALTER TABLE signals_dataproducts.{tbl} "
        f"DROP RANGE PARTITION {lo} <= VALUES < {hi}"
        for tbl in TIER0_TABLES
    ]


def walk(*, now_hour: int | None = None, apply_sql: bool = False) -> dict[str, Any]:
    """Walk the method. ``apply_sql`` is reserved for the Metaflow step."""
    fsm = get_method(DATA_PRODUCT_TIER_UPKEEP)
    doc = plan(now_hour)
    fsm.step("adding")
    doc["add_sql"] = add_sql(doc["add"]["lo"], doc["add"]["hi"])
    if apply_sql:
        raise NotImplementedError("Impala apply lives in the Metaflow flow")
    if doc["settle"] is None:
        fsm.step("settled")
        doc["fsm"] = fsm.as_method()
        return doc
    fsm.step("copying")
    fsm.step("verifying")
    if fsm.current != "verifying":
        raise RuntimeError("refuse DROP: not in verifying")
    fsm.step("dropping")
    doc["drop_sql"] = drop_sql(doc["settle"]["lo"], doc["settle"]["hi"])
    fsm.step("settled")
    doc["fsm"] = fsm.as_method()
    return doc
