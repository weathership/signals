"""gpu_metrics analog → Iceberg verify → DROP RANGE (no live Impala)."""

from __future__ import annotations

from signals.ops.gpu_metrics_settle import GURU, walk


def test_walk_plans_drop_for_closed_analoged_hour(monkeypatch) -> None:
    monkeypatch.setattr(
        "signals.ops.gpu_metrics_settle.hour_counts",
        lambda: {
            "iceberg": {100: 10},
            "kudu": {100: 10, 101: 3},
        },
    )
    doc = walk(apply=False, now_hour=101)
    assert doc["closed"] == [100]
    assert "DROP RANGE PARTITION VALUE = 100" in doc["planned"][0]["drop_sql"]
    assert doc["dropped"] == []


def test_walk_skips_live_hour(monkeypatch) -> None:
    monkeypatch.setattr(
        "signals.ops.gpu_metrics_settle.hour_counts",
        lambda: {"iceberg": {}, "kudu": {101: 4}},
    )
    doc = walk(apply=False, now_hour=101)
    assert doc["closed"] == []
    assert doc["planned"] == []


def test_walk_refuses_drop_when_iceberg_short(monkeypatch) -> None:
    monkeypatch.setattr(
        "signals.ops.gpu_metrics_settle.hour_counts",
        lambda: {"iceberg": {100: 2}, "kudu": {100: 10}},
    )
    try:
        walk(apply=False, now_hour=101)
    except RuntimeError as e:
        assert GURU in str(e)
        assert "refuse DROP" in str(e)
    else:
        raise AssertionError("expected refuse DROP")


def test_walk_marks_needs_analog_when_iceberg_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "signals.ops.gpu_metrics_settle.hour_counts",
        lambda: {"iceberg": {}, "kudu": {100: 10}},
    )
    doc = walk(apply=False, analog=True, now_hour=101)
    assert doc["planned"][0]["needs_analog"] is True


def test_airflow_dag_is_hourly_clock() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "k8s"
        / "airflow"
        / "dags"
        / "gpu_metrics_settle_dag.py"
    ).read_text(encoding="utf-8")
    assert 'schedule="5 * * * *"' in text
    assert "walk(apply=True" in text


def test_settle_sql_is_work_not_warehouse_clock() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "platform"
        / "gpu-metrics-settle.sql"
    ).read_text(encoding="utf-8")
    assert "SELECT cron.schedule" not in text
    assert "gpu_metrics_settle" in text
    assert "DROP RANGE PARTITION VALUE" in text
    assert "live hour stays on Kudu" in text
