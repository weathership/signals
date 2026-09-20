"""Airflow 3 backfill is how Theta remediates missed Monday windows."""
from __future__ import annotations

from types import SimpleNamespace

from signals.engine.airflow_api import AirflowClient


def test_create_backfill_is_one_interval_at_a_time():
    captured: dict = {}
    client = AirflowClient.__new__(AirflowClient)

    def _request(method, path, **kw):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kw.get("json")
        return SimpleNamespace(json=lambda: {"id": 9, "dag_id": "gaius_theta_cycle"})

    client._request = _request  # type: ignore[method-assign]
    out = client.create_backfill(
        "gaius_theta_cycle",
        from_date="2026-08-03T06:00:00+00:00",
        to_date="2026-09-14T06:00:00+00:00",
    )
    assert out["id"] == 9
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v2/backfills"
    body = captured["json"]
    assert body["dag_id"] == "gaius_theta_cycle"
    assert body["max_active_runs"] == 1
    assert body["run_backwards"] is True
    assert body["reprocess_behavior"] == "failed"


def test_create_backfill_dry_run_hits_dry_run_path():
    captured: dict = {}
    client = AirflowClient.__new__(AirflowClient)

    def _request(method, path, **kw):
        captured["path"] = path
        return SimpleNamespace(json=lambda: {"dag_id": "gaius_theta_cycle"})

    client._request = _request  # type: ignore[method-assign]
    client.create_backfill(
        "gaius_theta_cycle",
        from_date="2026-08-03T00:00:00+00:00",
        to_date="2026-09-14T00:00:00+00:00",
        dry_run=True,
    )
    assert captured["path"] == "/api/v2/backfills/dry_run"