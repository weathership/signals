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
