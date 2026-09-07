"""The Airflow side of Coordination Activities, as far as the Signals venv can run it.

``coord_lease`` (stdlib) is what both the trigger and the sensor rest on: fetch
the lease view, classify it, turn a terminal state into the hold's outcome. It
is exercised against a real local HTTP server. The trigger/sensor classes need
``airflow`` — absent from the Signals venv — so those tests skip with a reason;
they are constructed live inside the dag-processor pod by the deploy check.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2] / "config" / "k8s" / "airflow" / "plugins"
sys.path.insert(0, str(PLUGINS))

import coord_lease  # noqa: E402


class _Leases(BaseHTTPRequestHandler):
    views: dict[str, dict] = {}

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):  # noqa: N802
        aid = self.path.rsplit("/", 1)[-1]
        if aid == "boom":
            self.send_response(500)
            self.end_headers()
            return
        if aid == "garbage":
            body = b"not json"
            self.send_response(200)
        elif aid in self.views:
            body = json.dumps(self.views[aid]).encode()
            self.send_response(200)
        else:
            body = json.dumps({"activity_id": aid, "state": "unknown"}).encode()
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Leases)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/coord/activities"
    httpd.shutdown()


def test_poll_reads_the_state_signals_computed(server):
    _Leases.views["a1"] = {"activity_id": "a1", "state": "alive", "horizon_ns": 5}
    _Leases.views["r1"] = {"activity_id": "r1", "state": "released", "outcome": "hangup"}
    _Leases.views["l1"] = {"activity_id": "l1", "state": "lapsed"}
    assert coord_lease.poll(f"{server}/a1")[0] == coord_lease.ALIVE
    state, payload = coord_lease.poll(f"{server}/r1")
    assert state == coord_lease.RELEASED and payload["outcome"] == "hangup"
    assert coord_lease.poll(f"{server}/l1")[0] == coord_lease.LAPSED


def test_unknown_is_an_answer_not_an_outage(server):
    state, payload = coord_lease.poll(f"{server}/nope")
    assert state == coord_lease.UNKNOWN and payload["state"] == "unknown"
    assert coord_lease.outcome_for(state) is None


def test_outage_and_garbage_raise_unreachable(server):
    with pytest.raises(coord_lease.LeaseUnreachable):
        coord_lease.poll(f"{server}/boom")
    with pytest.raises(coord_lease.LeaseUnreachable):
        coord_lease.poll(f"{server}/garbage")
    with pytest.raises(coord_lease.LeaseUnreachable):
        coord_lease.poll("http://127.0.0.1:9/coord/activities/x", timeout_s=0.5)


def test_outcome_only_for_terminal_states():
    assert coord_lease.outcome_for(coord_lease.RELEASED) == "released"
    assert coord_lease.outcome_for(coord_lease.LAPSED) == "lapsed"
    assert coord_lease.outcome_for(coord_lease.ALIVE) is None
    assert coord_lease.outcome_for(coord_lease.UNKNOWN) is None
    assert coord_lease.classify({"state": "ALIVE"}) == coord_lease.ALIVE
    assert coord_lease.classify({"state": "weird"}) == coord_lease.UNKNOWN
    assert coord_lease.classify({}) == coord_lease.UNKNOWN


airflow = pytest.importorskip(
    "airflow", reason="airflow is not installed in the Signals venv; the trigger/sensor are constructed live in the dag-processor pod by the deploy check"
)


def test_trigger_and_sensor_construct():
    import coord_signals

    trig = coord_signals.SignalsLeaseTrigger(activity_id="x", lease_url="http://h/coord/activities/x")
    assert trig.serialize()[0] == "coord_signals.SignalsLeaseTrigger"
    dag = coord_signals.make_coord_dag("coord_test", description="t", pool="agent_rtc")
    hold = dag.get_task("hold")
    assert hold.pool == "agent_rtc" and hold.deferrable and "lease_url" in hold.template_fields


# ── 2026-09-07: the run declares ITSELF (POST /coord/activities) ─────────────


class _Declare(BaseHTTPRequestHandler):
    posted: list = []

    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(n).decode() or "{}")
        _Declare.posted.append((self.path, payload))
        if payload.get("peer") == "stranger":
            body = json.dumps({"error": "#CO.00000001.UNKNOWNPEER peer 'stranger'", "guru": "#CO.00000001.UNKNOWNPEER"}).encode()
            self.send_response(400)
        else:
            aid = "22222222-3333-4444-5555-666666666666"
            body = json.dumps({"activity_id": aid, "state": "alive", "lease_url": f"http://h/coord/activities/{aid}", "activity_state": "running"}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def declare_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Declare)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_post_json_declares_and_surfaces_refusals(declare_server):
    view = coord_lease.post_json(f"{declare_server}/coord/activities", {"kind": "k", "peer": "gaius", "dag_id": "d", "run_id": "r"})
    assert view["activity_id"] and view["lease_url"].endswith(view["activity_id"])
    assert _Declare.posted[-1][0] == "/coord/activities" and _Declare.posted[-1][1]["peer"] == "gaius"
    with pytest.raises(coord_lease.DeclareRefused) as e:
        coord_lease.post_json(f"{declare_server}/coord/activities", {"kind": "k", "peer": "stranger"})
    assert e.value.status == 400 and "UNKNOWNPEER" in e.value.body["guru"]
    with pytest.raises(coord_lease.LeaseUnreachable):
        coord_lease.post_json("http://127.0.0.1:9/coord/activities", {}, timeout_s=0.5)


@pytest.mark.skipif("airflow" not in sys.modules and pytest.importorskip("airflow", reason="airflow not in the Signals venv") is None, reason="airflow absent")
def test_workload_and_chain_dags_construct():
    import coord_signals

    wl = coord_signals.make_workload_dag(
        "wl_test", kind="article_curate", peer="gaius",
        claims=[{"leaf": "root.internal.inference.extract", "gpu": 1}], horizon_s=7200, schedule="7 9 * * *", reason="t",
    )
    assert [t.task_id for t in wl.tasks] == ["declare", "hold", "close"]
    assert isinstance(wl.get_task("declare"), coord_signals.SignalsDeclareOperator)
    assert "xcom_pull(task_ids='declare'" in wl.get_task("hold").lease_url
    assert any(a.name == "zndx.coord.article_curate.ended" for a in wl.get_task("close").outlets)
    chain = coord_signals.make_chain_dag(
        "chain_test",
        [
            {"name": "curate", "kind": "article_curate", "peer": "gaius", "claims": [{"leaf": "root.internal.inference.extract", "gpu": 1}], "horizon_s": 7200},
            {"name": "publish", "kind": "publish_cards", "peer": "gaius", "claims": [], "horizon_s": 3600},
        ],
        schedule=None,
    )
    ids = [t.task_id for t in chain.tasks]
    assert {"declare_curate", "hold_curate", "close_curate", "declare_publish", "hold_publish", "close_publish"} <= set(ids)
    assert "declare_publish" in chain.get_task("close_curate").downstream_task_ids


@pytest.mark.skipif("airflow" not in sys.modules and pytest.importorskip("airflow", reason="airflow not in the Signals venv") is None, reason="airflow absent")
def test_workload_schedule_shapes():
    """protocol ce31d5d after_mode: all → AssetAll list, any → AssetAny, cron+after → AssetOrTimeSchedule."""
    import coord_signals as cs
    from airflow.sdk import AssetAny
    from airflow.timetables.assets import AssetOrTimeSchedule

    assert cs.workload_schedule(cron="13 1 * * *") == "13 1 * * *"
    assert cs.workload_schedule() is None
    y = cs.workload_schedule(after_kinds=["a", "b"])
    assert [a.name for a in y] == ["zndx.coord.a.ended", "zndx.coord.b.ended"]
    z = cs.workload_schedule(after_kinds=["a", "b"], after_mode="any")
    assert isinstance(z, AssetAny) and "any" in z.as_expression()
    w = cs.workload_schedule(cron="0 0 * * *", after_kinds=["a", "b"], after_mode="any", timezone_name="America/Chicago")
    assert isinstance(w, AssetOrTimeSchedule) and w.summary == "Asset or 0 0 * * *"
    assert "any" in w.asset_condition.as_expression()
    with pytest.raises(ValueError):
        cs.workload_schedule(after_kinds=["a"], after_mode="some")
    d = cs.make_workload_dag("wl_any", kind="agenda_brief", peer="gaius", claims=[], horizon_s=1800, schedule=w, reason="t", paused=True)
    assert d.timetable.summary == "Asset or 0 0 * * *" and [t.task_id for t in d.tasks] == ["declare", "hold", "close"]
