"""C2 last-gasp / preempted heartbeat calls Engine/Yield."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

from signals.c2.parse import parse_heartbeat
from signals.c2.server import C2State, make_handler


def test_parse_minifi_shaped_heartbeat():
    meta = parse_heartbeat(
        {
            "agentInfo": {"identifier": "agent-9", "workload_id": "wl-a"},
            "phase": "preempted",
            "project": "gaius",
        }
    )
    assert meta["workload_id"] == "wl-a"
    assert meta["sentinel_id"] == "agent-9"
    assert meta["project"] == "gaius"
    assert meta["phase"] == "preempted"


def test_last_gasp_invokes_yield():
    calls: list[dict] = []

    def fake_yield(target, **kwargs):
        rec = {"target": target, **kwargs}
        calls.append(rec)
        return {"ok": True, "process_ended": True, "message": "ended", **rec}

    state = C2State(yield_fn=fake_yield, orphan_after_s=3600)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    port = httpd.server_address[1]
    Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps(
            {
                "workload_id": "proof-c2",
                "project": "signals",
                "sentinel_id": "sent-1",
                "phase": "preempted",
            }
        )
        conn.request(
            "POST",
            "/c2-protocol/last-gasp",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        assert resp.status == 200
        assert data["yield"]["process_ended"] is True
        assert calls and calls[0]["workload_id"] == "proof-c2"
        assert calls[0]["reason"] == "PREEMPTED"
    finally:
        httpd.shutdown()
