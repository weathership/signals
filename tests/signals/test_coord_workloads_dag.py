"""coord_workloads_dag — the dynamic workload-DAG module, as far as the Signals venv can run it.

The module imports airflow / coord_signals and reads the registry Variable at import time;
without airflow in the venv those are stubbed (an absent Variable is an empty catalogue),
which is exactly the parse-time path the dag-processor runs. `test_coord_signals_trigger.py`
skips as a whole module without airflow (its skip markers evaluate at import), so the
DAG-module tests live here.
"""

from __future__ import annotations

import sys
from pathlib import Path


def test_workload_dag_start_date_is_the_enable_moment(monkeypatch):
    """coord_workloads_dag._start_date: enabled_since_ns → tz-aware start_date; legacy rows keep
    the fixed migration date. The module imports airflow/coord_signals and reads the registry
    Variable at import; without airflow in the venv those are stubbed (an absent Variable is an
    empty catalogue), which is exactly the parse-time path the dag-processor runs."""
    import importlib
    import types
    from datetime import datetime, timezone as dt_tz
    from zoneinfo import ZoneInfo

    dags_dir = Path(__file__).resolve().parents[2] / "config" / "k8s" / "airflow" / "dags"
    monkeypatch.syspath_prepend(str(dags_dir))
    try:
        import airflow  # noqa: F401
    except ImportError:
        airflow_mod = types.ModuleType("airflow")
        models_mod = types.ModuleType("airflow.models")

        class _Variable:
            @staticmethod
            def get(key, default_var=None, deserialize_json=False):
                return default_var

        models_mod.Variable = _Variable  # type: ignore[attr-defined]
        airflow_mod.models = models_mod  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "airflow", airflow_mod)
        monkeypatch.setitem(sys.modules, "airflow.models", models_mod)
        cs_stub = types.ModuleType("coord_signals")
        cs_stub.make_workload_dag = lambda *a, **k: None  # type: ignore[attr-defined]
        cs_stub.workload_schedule = lambda **k: None  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "coord_signals", cs_stub)
    monkeypatch.delitem(sys.modules, "coord_workloads_dag", raising=False)
    mod = importlib.import_module("coord_workloads_dag")

    since = datetime(2026, 9, 7, 21, 22, 23, tzinfo=dt_tz.utc)
    ns = int(since.timestamp() * 1_000_000_000)
    utc = mod._start_date({"enabled_since_ns": ns})
    assert utc == since and utc.tzinfo is not None
    chi = mod._start_date({"enabled_since_ns": ns, "timezone": "America/Chicago"})
    assert chi == since and chi.tzinfo == ZoneInfo("America/Chicago") and chi.hour == 16
    legacy = mod._start_date({"cron": "0 0 * * *"})
    assert legacy == mod.CATALOGUE_START
    legacy_tz = mod._start_date({"timezone": "America/Chicago", "enabled_since_ns": 0})
    assert legacy_tz == mod.CATALOGUE_START and legacy_tz.tzinfo == ZoneInfo("America/Chicago")
    monkeypatch.delitem(sys.modules, "coord_workloads_dag", raising=False)
