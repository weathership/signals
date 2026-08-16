"""data-product.tier-upkeep plan + YK proxy sentinel stamp."""

from pathlib import Path

from signals.ops.tier_upkeep import YK_APP_ID, YK_QUEUE, plan, walk


def test_plan_add_is_next_week() -> None:
    doc = plan(now_hour=2954 * 168 + 3)
    assert doc["yk_app_id"] == YK_APP_ID
    assert doc["yk_queue"] == YK_QUEUE
    assert doc["add"]["hi"] - doc["add"]["lo"] == 168
    assert doc["add"]["lo"] == 2955 * 168
    assert doc["settle"] is not None
    assert doc["settle"]["hi"] == 2950 * 168


def test_walk_reaches_settled_and_plans_drop() -> None:
    doc = walk(now_hour=2954 * 168, apply_sql=False)
    assert doc["fsm"]["current"] == "settled"
    assert doc["add_sql"]
    assert "DROP RANGE PARTITION" in doc["drop_sql"][0]
    assert all("details_tier0" in s or "tx_tier0" in s or "hx_" in s for s in doc["drop_sql"])


def test_flow_end_records_snapshot_product() -> None:
    text = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "signals"
        / "flows"
        / "tier_upkeep.py"
    ).read_text(encoding="utf-8")
    assert "record_from_current" in text
    assert "signals.ops.metaflow_store" in text
    assert '"upkeep"' in text or "upkeep" in text


def test_proxy_sentinel_stamps_platform_queue() -> None:
    text = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "platform"
        / "tier-upkeep-sentinel.yaml"
    ).read_text(encoding="utf-8")
    assert "signals-dataproduct-tier-upkeep" in text
    assert "root.platform" in text
    assert "proxy-flow" in text
    assert "federation.project: signals" in text
    assert "yunikorn.apache.org/queue: root.platform" in text
