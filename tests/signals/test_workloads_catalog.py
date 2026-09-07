"""Workload catalogue: engines submit ScheduleHints, Signals materialises them.

Pins: validation (peer, id/kind, claims vs leaf max, `after` must resolve),
replace semantics (absent → paused, kept), engine_declared entries carry no
dag_id, dag_id assignment, the Airflow Variable is written only when the
registry content changed, pause flips reach existing DAGs, resume republishes.
"""

from __future__ import annotations

import json

import pytest

from signals.engine import workloads_catalog as wc
from signals.engine.airflow_api import AirflowError, GURU_API
from signals.engine.generated.zndx.engine.v1 import engine_pb2

LEAF_MAX = {
    "root.internal.inference.extract": 2,
    "root.internal.inference.light": 2,
    "root.internal.inference.agent-rtc": 1,
}


class FakeAirflow:
    def __init__(self):
        self.variables: dict[str, str] = {}
        self.paused: dict[str, bool] = {}
        self.known_dags: set[str] = set()
        self.calls: list[tuple] = []
        self.fail_variables = False

    def get_variable(self, key):
        self.calls.append(("get_variable", key))
        return self.variables.get(key)

    def set_variable(self, key, value, *, description=""):
        self.calls.append(("set_variable", key))
        if self.fail_variables:
            raise AirflowError(GURU_API, "Airflow API PATCH /api/v2/variables → HTTP 503: down", "wait")
        self.variables[key] = value
        return {"key": key, "value": value}

    def set_paused(self, dag_id, paused):
        self.calls.append(("set_paused", dag_id, paused))
        if dag_id not in self.known_dags:
            raise AirflowError(GURU_API, f"Airflow API PATCH /api/v2/dags/{dag_id} → HTTP 404: not found", "wait")
        self.paused[dag_id] = paused
        return {"dag_id": dag_id, "is_paused": paused}


class Clock:
    def __init__(self, ns=1_000):
        self.ns = ns

    def __call__(self):
        return self.ns


def _hint(id_, kind, *, cron="", after=(), claims=(), enabled=True, source="airflow", dag_id="", horizon_s=7200):
    h = engine_pb2.ScheduleHint(
        id=id_, kind=kind, cron=cron, airflow_dag_id=dag_id, source=source, enabled=enabled,
        horizon_s=horizon_s, after=list(after), runner="task", description=f"{kind} test",
    )
    for leaf, gpu in claims:
        h.claims.add(leaf=leaf, gpu=gpu)
    return h


def _catalog(tmp_path, fake):
    return wc.WorkloadCatalog(tmp_path / "workloads", fake, leaf_max=LEAF_MAX.get, clock_ns=Clock())


def _registry(fake):
    return json.loads(fake.variables[wc.VARIABLE_KEY])


def test_sync_materialises_and_publishes(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    out = cat.sync(
        "gaius",
        [_hint("task.article_curate", "article_curate", cron="7 9 * * *",
               claims=[("root.internal.inference.extract", 1)], dag_id="gaius_article_curate")],
        replace=True, engine_build="abc123",
    )
    assert [e.state for e in out] == [wc.STATE_MATERIALIZED]
    reg = _registry(fake)
    assert reg["version"] == 1
    row = reg["workloads"][0]
    assert row["dag_id"] == "gaius_article_curate" and row["cron"] == "7 9 * * *"
    assert row["claims"] == [{"leaf": "root.internal.inference.extract", "gpu": 1}]
    assert row["engine_build"] == "abc123" and row["enabled"] is True
    # ListWorkloads shape
    rec = out[0].to_record()
    assert rec.peer == "gaius" and rec.dag_id == "gaius_article_curate" and rec.state == "materialized"
    assert rec.workload.claims[0].gpu == 1


def test_dag_id_default_and_engine_declared(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    out = cat.sync(
        "hermes",
        [
            _hint("interactive.agent_rtc", "interactive_session", source="engine",
                  claims=[("root.internal.inference.agent-rtc", 1)], horizon_s=3600),
            _hint("task.something", "something", cron="0 * * * *"),
        ],
        replace=True,
    )
    by_id = {e.id: e for e in out}
    assert by_id["interactive.agent_rtc"].state == wc.STATE_ENGINE_DECLARED
    assert by_id["interactive.agent_rtc"].dag_id == ""
    assert by_id["task.something"].dag_id == "hermes_something"
    rows = {r["id"]: r for r in _registry(fake)["workloads"]}
    assert rows["interactive.agent_rtc"]["dag_id"] == ""  # published for visibility, no DAG generated


def test_after_resolves_kinds_or_errors(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    out = cat.sync(
        "gaius",
        [
            _hint("task.article_curate", "article_curate", cron="7 9 * * *"),
            _hint("task.publish_cards", "publish_cards", after=["task.article_curate"]),
            _hint("task.orphan", "orphan", after=["task.nowhere"]),
            _hint("task.both", "both", cron="* * * * *", after=["task.article_curate"]),
        ],
        replace=True,
    )
    by_id = {e.id: e for e in out}
    assert by_id["task.publish_cards"].state == wc.STATE_MATERIALIZED
    assert by_id["task.publish_cards"].after_kinds == ["article_curate"]
    assert by_id["task.orphan"].state == wc.STATE_ERROR and "no such catalogue id" in by_id["task.orphan"].error
    assert by_id["task.both"].state == wc.STATE_ERROR and "both cron and after" in by_id["task.both"].error
    # errored entries are recorded (ListWorkloads) but never published to Airflow
    assert {r["id"] for r in _registry(fake)["workloads"]} == {"task.article_curate", "task.publish_cards"}
    assert [r for r in _registry(fake)["workloads"] if r["id"] == "task.publish_cards"][0]["after_kinds"] == ["article_curate"]


def test_after_may_reference_another_peer(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    cat.sync("gaius", [_hint("task.article_curate", "article_curate", cron="7 9 * * *")], replace=True)
    out = cat.sync("aegir", [_hint("task.digest", "digest", after=["task.article_curate"])], replace=True)
    assert out[0].state == wc.STATE_MATERIALIZED and out[0].after_kinds == ["article_curate"]


def test_claims_validated_against_leaf_max(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    out = cat.sync(
        "gaius",
        [
            _hint("task.big", "big", cron="0 0 * * *", claims=[("root.internal.inference.extract", 3)]),
            _hint("task.where", "where", cron="0 0 * * *", claims=[("root.internal.inference.nowhere", 1)]),
        ],
        replace=True,
    )
    by_id = {e.id: e for e in out}
    assert "exceeds the leaf max 2" in by_id["task.big"].error
    assert "unknown YK leaf" in by_id["task.where"].error


def test_unknown_peer_refused(tmp_path):
    cat = _catalog(tmp_path, FakeAirflow())
    with pytest.raises(wc.CatalogError, match="unknown peer"):
        cat.sync("mallory", [_hint("x", "x")], replace=True)


def test_replace_pauses_absent_entries_and_keeps_history(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    cat.sync(
        "gaius",
        [_hint("task.a", "a", cron="0 1 * * *"), _hint("task.b", "b", cron="0 2 * * *")],
        replace=True,
    )
    fake.known_dags.add("gaius_b")  # the processor has registered it by now
    out = cat.sync("gaius", [_hint("task.a", "a", cron="0 1 * * *")], replace=True)
    by_id = {e.id: e for e in out}
    assert by_id["task.b"].state == wc.STATE_PAUSED and by_id["task.b"].enabled is False
    assert by_id["task.a"].state == wc.STATE_MATERIALIZED
    rows = {r["id"]: r for r in _registry(fake)["workloads"]}
    assert rows["task.b"]["enabled"] is False  # still published → DAG stays visible, paused
    assert ("set_paused", "gaius_b", True) in fake.calls  # the flip reached the existing DAG


def test_non_replace_merges(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    cat.sync("gaius", [_hint("task.a", "a", cron="0 1 * * *")], replace=True)
    out = cat.sync("gaius", [_hint("task.b", "b", cron="0 2 * * *")], replace=False)
    assert {e.id: e.state for e in out} == {"task.a": wc.STATE_MATERIALIZED, "task.b": wc.STATE_MATERIALIZED}


def test_variable_written_only_on_change(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    hints = [_hint("task.a", "a", cron="0 1 * * *")]
    cat.sync("gaius", hints, replace=True)
    writes = [c for c in fake.calls if c[0] == "set_variable"]
    assert len(writes) == 1
    cat.sync("gaius", hints, replace=True)  # identical content
    writes = [c for c in fake.calls if c[0] == "set_variable"]
    assert len(writes) == 1
    assert _registry(fake)["version"] == 1
    cat.sync("gaius", [_hint("task.a", "a", cron="0 3 * * *")], replace=True)  # changed cron
    writes = [c for c in fake.calls if c[0] == "set_variable"]
    assert len(writes) == 2
    assert _registry(fake)["version"] == 2


def test_variable_rewritten_when_remote_lost_it(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    hints = [_hint("task.a", "a", cron="0 1 * * *")]
    cat.sync("gaius", hints, replace=True)
    fake.variables.clear()  # Airflow metadata reset
    cat.sync("gaius", hints, replace=True)
    assert wc.VARIABLE_KEY in fake.variables


def test_airflow_down_keeps_catalogue_and_resume_republishes(tmp_path):
    fake = FakeAirflow()
    fake.fail_variables = True
    cat = _catalog(tmp_path, fake)
    with pytest.raises(AirflowError):
        cat.sync("gaius", [_hint("task.a", "a", cron="0 1 * * *")], replace=True)
    assert [e.id for e in cat.list("gaius")] == ["task.a"]  # stored despite the publish failure
    assert wc.VARIABLE_KEY not in fake.variables
    fake.fail_variables = False
    cat2 = _catalog(tmp_path, fake)  # a new engine process
    assert cat2.resume() is True
    assert _registry(fake)["workloads"][0]["id"] == "task.a"
    assert cat2.resume() is False  # nothing pending


def test_duplicate_ids_in_one_sync_error(tmp_path):
    fake = FakeAirflow()
    cat = _catalog(tmp_path, fake)
    out = cat.sync("gaius", [_hint("task.a", "a", cron="0 1 * * *"), _hint("task.a", "a2", cron="0 2 * * *")], replace=True)
    assert any(e.state == wc.STATE_ERROR and "duplicate" in e.error for e in out)
