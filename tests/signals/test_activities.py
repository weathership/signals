"""Coordination Activities: ActivityService against a fake Airflow.

Pins the lifecycle the protocol spec promises (coordination_activities.md):
idempotent declare, renew = new run + previous SUPERSEDED, release note →
RELEASED, unnoted success → EXPIRED, failed → FAILED, list coalescing by
activity_id (highest n wins), watch emits on change and on heartbeat.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signals.engine import activities as act
from signals.engine.generated.zndx.engine.v1 import engine_pb2
from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2

NS = 1_000_000_000


class FakeAirflow:
    """Enough of the API v2 surface for ActivityService, in memory."""

    def __init__(self, *, paused: bool = True):
        self.runs: dict[str, dict] = {}
        self.paused = paused
        self.calls: list[tuple] = []
        self.now_iso = "2026-09-06T23:00:00+00:00"

    def get_dag(self, dag_id):
        self.calls.append(("get_dag", dag_id))
        return {"dag_id": dag_id, "is_paused": self.paused}

    def set_paused(self, dag_id, paused):
        self.calls.append(("set_paused", dag_id, paused))
        self.paused = paused
        return {"dag_id": dag_id, "is_paused": paused}

    def trigger_dag_run(self, dag_id, run_id, conf, *, logical_date=None, note=None):
        self.calls.append(("trigger", run_id))
        if run_id in self.runs:  # Airflow 409 → existing run
            return dict(self.runs[run_id])
        run = {
            "dag_id": dag_id,
            "dag_run_id": run_id,
            "state": "running",
            "conf": dict(conf),
            "note": note,
            "end_date": None,
        }
        self.runs[run_id] = run
        return dict(run)

    def get_dag_run(self, dag_id, run_id):
        return dict(self.runs[run_id])

    def list_dag_runs(self, dag_id, *, states=None, limit=200, order_by="-run_after", run_id_pattern=None):
        rows = list(self.runs.values())
        if run_id_pattern:
            rows = [r for r in rows if run_id_pattern in r["dag_run_id"]]
        if states:
            rows = [r for r in rows if r["state"] in states]
        return [dict(r) for r in rows][:limit]

    def patch_dag_run(self, dag_id, run_id, *, state=None, note=None):
        self.calls.append(("patch", run_id, state, note))
        run = self.runs[run_id]
        if state is not None:
            run["state"] = state
            if state in ("success", "failed"):
                run["end_date"] = self.now_iso
        if note is not None:
            run["note"] = note
        return dict(run)


class Clock:
    def __init__(self, ns: int):
        self.ns = ns

    def __call__(self) -> int:
        return self.ns


def _svc(fake: FakeAirflow, clock: Clock, **kw) -> act.ActivityService:
    return act.ActivityService(fake, clock_ns=clock, sleep=lambda _s: None, **kw)


def _declare_req(peer="hermes", request_id="req-1", horizon_ns=2_000 * NS, **kw):
    req = scheduler_pb2.DeclareActivityRequest(
        peer=peer,
        request_id=request_id,
        kind=kw.get("kind", "interactive_session"),
        owner=kw.get("owner", "rtc-42"),
        horizon_ns=horizon_ns,
        precludes=kw.get("precludes", []),
        reason=kw.get("reason", "webrtc session"),
    )
    req.claims.add(leaf="root.internal.inference.agent-rtc", gpu=1)
    req.postures["gaius.endpoint.thinking"] = "hold-uptime"
    return req


def test_declare_unpauses_and_is_idempotent():
    fake, clock = FakeAirflow(paused=True), Clock(1_000 * NS)
    svc = _svc(fake, clock)
    a = svc.declare(_declare_req())
    b = svc.declare(_declare_req())  # retry with the same request_id
    assert a.activity_id == b.activity_id == act.activity_id_for("hermes", "req-1")
    assert a.run_id == b.run_id == act.run_id_for(a.activity_id, 1)
    assert a.state == engine_pb2.ACTIVITY_RUNNING and a.in_force
    assert ("set_paused", "coord_activity", False) in fake.calls
    assert len([c for c in fake.calls if c[0] == "trigger"]) == 2  # second → 409 path
    conf = fake.runs[a.run_id]["conf"]
    assert conf["postures"] == {"gaius.endpoint.thinking": "hold-uptime"}
    assert conf["claims"] == [{"leaf": "root.internal.inference.agent-rtc", "gpu": 1}]
    assert conf["horizon_iso"] == datetime.fromtimestamp(2000, tz=timezone.utc).isoformat()
    p = a.to_proto()
    assert p.peer == "hermes" and p.postures["gaius.endpoint.thinking"] == "hold-uptime"
    assert p.claims[0].leaf.endswith("agent-rtc") and p.claims[0].gpu == 1


def test_declare_refuses_unknown_peer_and_past_horizon():
    fake, clock = FakeAirflow(), Clock(1_000 * NS)
    svc = _svc(fake, clock)
    with pytest.raises(act.ActivityError) as e:
        svc.declare(_declare_req(peer="stranger"))
    assert e.value.guru == act.GURU_UNKNOWNPEER
    with pytest.raises(act.ActivityError) as e2:
        svc.declare(_declare_req(horizon_ns=999 * NS))
    assert e2.value.guru == act.GURU_HORIZON
    assert not fake.runs  # nothing reached Airflow


def test_renew_supersedes_previous_run():
    fake, clock = FakeAirflow(), Clock(1_000 * NS)
    svc = _svc(fake, clock)
    a = svc.declare(_declare_req())
    clock.ns = 1_500 * NS
    r = svc.renew("hermes", a.activity_id, 3_000 * NS)
    assert r.run_id == act.run_id_for(a.activity_id, 2) and r.n == 2
    assert r.horizon_ns == 3_000 * NS and r.renewed_ns == 1_500 * NS
    prev = fake.runs[a.run_id]
    assert prev["state"] == "success" and prev["note"] == f"renewed → {r.run_id}"
    assert act.state_of_run(prev) == engine_pb2.ACTIVITY_SUPERSEDED
    # list coalesces by activity_id → the renewal, in force
    recs = svc.list(peer="hermes")
    assert [x.run_id for x in recs] == [r.run_id]
    assert recs[0].in_force
    # renewing again with a past horizon is refused; the other peer cannot touch it
    with pytest.raises(act.ActivityError) as e:
        svc.renew("hermes", a.activity_id, 1_400 * NS)
    assert e.value.guru == act.GURU_HORIZON
    with pytest.raises(act.ActivityError) as e2:
        svc.release("gaius", a.activity_id, "not mine")
    assert e2.value.guru == act.GURU_NOTOWNER


def test_release_then_terminal_semantics():
    fake, clock = FakeAirflow(), Clock(1_000 * NS)
    svc = _svc(fake, clock)
    a = svc.declare(_declare_req())
    clock.ns = 1_200 * NS
    rel = svc.release("hermes", a.activity_id, "hangup")
    assert rel.state == engine_pb2.ACTIVITY_RELEASED
    assert rel.note == "released by hermes: hangup" and rel.ended_ns > 0
    assert not rel.in_force
    with pytest.raises(act.ActivityError) as e:
        svc.release("hermes", a.activity_id, "again")
    assert e.value.guru == act.GURU_ENDED
    with pytest.raises(act.ActivityError) as e2:
        svc.renew("hermes", a.activity_id, 5_000 * NS)
    assert e2.value.guru == act.GURU_ENDED
    assert svc.list(active_only=True) == []
    assert [x.activity_id for x in svc.list()] == [a.activity_id]
    with pytest.raises(act.ActivityError) as e3:
        svc.release("hermes", "00000000-0000-0000-0000-000000000000", "x")
    assert e3.value.guru == act.GURU_NOTFOUND


def test_state_mapping_expired_failed_queued():
    base = {"conf": {"activity_id": "x"}}
    assert act.state_of_run({**base, "state": "queued"}) == engine_pb2.ACTIVITY_QUEUED
    assert act.state_of_run({**base, "state": "running"}) == engine_pb2.ACTIVITY_RUNNING
    assert act.state_of_run({**base, "state": "success", "note": None}) == engine_pb2.ACTIVITY_EXPIRED
    assert act.state_of_run({**base, "state": "success", "note": "released by hermes: bye"}) == engine_pb2.ACTIVITY_RELEASED
    assert act.state_of_run({**base, "state": "success", "note": "renewed → act-x-2"}) == engine_pb2.ACTIVITY_SUPERSEDED
    assert act.state_of_run({**base, "state": "failed"}) == engine_pb2.ACTIVITY_FAILED
    assert act.ActivityRecord.from_run({"state": "running", "conf": {}}) is None


def test_watch_emits_on_change_and_heartbeat_and_drops_old_ended():
    fake, clock = FakeAirflow(), Clock(1_000 * NS)
    svc = _svc(fake, clock, heartbeat_s=60, ended_window_s=600)
    a = svc.declare(_declare_req())
    ticks = {"n": 0}
    events: list[tuple[list[act.ActivityRecord], int]] = []

    def is_active() -> bool:
        ticks["n"] += 1
        return ticks["n"] <= 40

    gen = svc.watch(is_active=is_active)
    recs, at = next(gen)
    assert [r.run_id for r in recs] == [a.run_id] and at == 1_000 * NS
    # no change, inside the heartbeat → nothing emitted on the next poll
    clock.ns = 1_010 * NS
    # advance to a change: release → emitted once with RELEASED (ended within window)
    fake.now_iso = datetime.fromtimestamp(1_010, tz=timezone.utc).isoformat()
    svc.release("hermes", a.activity_id, "hangup")
    recs, at = next(gen)
    assert recs[0].state == engine_pb2.ACTIVITY_RELEASED and at == 1_010 * NS
    # heartbeat: same set, 60 s later → emitted again
    clock.ns = 1_071 * NS
    recs, at = next(gen)
    assert at == 1_071 * NS and recs[0].state == engine_pb2.ACTIVITY_RELEASED
    # past the ended window the released activity leaves the set (a change → emitted)
    clock.ns = 1_700 * NS
    recs, at = next(gen)
    assert recs == [] and at == 1_700 * NS
    events.append((recs, at))
    gen.close()


def test_watch_event_proto_shape():
    fake, clock = FakeAirflow(), Clock(1_000 * NS)
    svc = _svc(fake, clock)
    a = svc.declare(_declare_req(precludes=["root.internal.inference.light"]))
    ev = act.watch_event([a], 1_000 * NS)
    assert ev.observed_ns == 1_000 * NS
    assert ev.activities[0].activity_id == a.activity_id
    assert list(ev.activities[0].precludes) == ["root.internal.inference.light"]
    assert ev.activities[0].state == engine_pb2.ACTIVITY_RUNNING
