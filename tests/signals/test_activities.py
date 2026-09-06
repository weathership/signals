"""Coordination Activities: ActivityService + LeaseStore against a fake Airflow.

Pins the OBSERVE model the protocol spec promises (coordination_activities.md):
declare writes the lease first and triggers ONE run whose conf carries the
lease_url; renew is a heartbeat (no Airflow call, no new run); release flips
the lease and touches only the run's note; run success reads RELEASED vs
EXPIRED from the lease; failed → FAILED; the interactive kind gets its own DAG
and the agent_rtc pool; the lease-state function the sensor rests on; watch
emits on change and on heartbeat.
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
        self.pools: dict[str, dict] = {}
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

    def ensure_pool(self, name, *, slots, include_deferred=True, description=""):
        self.calls.append(("ensure_pool", name, slots, include_deferred))
        self.pools.setdefault(name, {"name": name, "slots": slots, "include_deferred": include_deferred})
        return self.pools[name]

    def trigger_dag_run(self, dag_id, run_id, conf, *, logical_date=None, note=None):
        self.calls.append(("trigger", dag_id, run_id))
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
        self.calls.append(("get_run", run_id))
        return dict(self.runs[run_id])

    def list_dag_runs(self, dag_id, *, states=None, limit=200, order_by="-run_after", run_id_pattern=None):
        rows = [r for r in self.runs.values() if r["dag_id"] == dag_id]
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

    # what the sensor would do once it observes the lease
    def finish(self, run_id, state="success"):
        self.runs[run_id]["state"] = state
        self.runs[run_id]["end_date"] = self.now_iso


class Clock:
    def __init__(self, ns: int):
        self.ns = ns

    def __call__(self) -> int:
        return self.ns


@pytest.fixture
def leases(tmp_path):
    return act.LeaseStore(tmp_path / "activities", ttl_s=180)


def _svc(fake: FakeAirflow, clock: Clock, leases: act.LeaseStore, **kw) -> act.ActivityService:
    return act.ActivityService(
        fake, leases, lease_url_base="http://signals-engine-control:50552", clock_ns=clock, sleep=lambda _s: None, **kw
    )


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


def test_declare_writes_lease_first_then_one_run_with_lease_url_and_pool(leases):
    fake, clock = FakeAirflow(paused=True), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    a = svc.declare(_declare_req())
    aid = act.activity_id_for("hermes", "req-1")
    assert a.activity_id == aid and a.run_id == f"act-{aid}" and a.dag_id == "coord_interactive_session"
    assert a.state == engine_pb2.ACTIVITY_RUNNING and a.in_force
    assert ("set_paused", "coord_interactive_session", False) in fake.calls
    assert ("ensure_pool", "agent_rtc", 1, True) in fake.calls
    lease = leases.read(aid)
    assert lease and lease["heartbeat_ns"] == 1_000 * NS and lease["released"] is False and lease["lease_ttl_s"] == 180
    conf = fake.runs[a.run_id]["conf"]
    assert conf["lease_url"] == f"http://signals-engine-control:50552/coord/activities/{aid}"
    assert conf["postures"] == {"gaius.endpoint.thinking": "hold-uptime"}
    assert conf["claims"] == [{"leaf": "root.internal.inference.agent-rtc", "gpu": 1}]
    assert conf["horizon_iso"] == datetime.fromtimestamp(2000, tz=timezone.utc).isoformat()
    assert "n" not in conf  # one run per activity — renewals are heartbeats
    p = a.to_proto()
    assert p.postures["gaius.endpoint.thinking"] == "hold-uptime" and p.claims[0].gpu == 1


def test_declare_is_idempotent_and_does_not_heartbeat(leases):
    fake, clock = FakeAirflow(), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    a = svc.declare(_declare_req())
    clock.ns = 1_100 * NS
    b = svc.declare(_declare_req())  # retry with the same request_id
    assert a.activity_id == b.activity_id and a.run_id == b.run_id
    assert len([c for c in fake.calls if c[0] == "trigger"]) == 1  # no second run
    assert leases.read(a.activity_id)["heartbeat_ns"] == 1_000 * NS  # a retry is not a renew


def test_generic_kind_uses_coord_activity_without_pool(leases):
    fake, clock = FakeAirflow(paused=False), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    a = svc.declare(_declare_req(request_id="cw", kind="curation_window"))
    assert a.dag_id == "coord_activity"
    assert not [c for c in fake.calls if c[0] == "ensure_pool"]


def test_declare_refuses_unknown_peer_and_past_horizon(leases):
    fake, clock = FakeAirflow(), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    with pytest.raises(act.ActivityError) as e1:
        svc.declare(_declare_req(peer="stranger"))
    assert e1.value.guru == act.GURU_UNKNOWNPEER
    with pytest.raises(act.ActivityError) as e2:
        svc.declare(_declare_req(horizon_ns=999 * NS))
    assert e2.value.guru == act.GURU_HORIZON
    assert not fake.runs and not list(leases.root.glob("*.json"))


def test_trigger_failure_leaves_no_lease(leases):
    class Broken(FakeAirflow):
        def trigger_dag_run(self, *a, **k):
            from signals.engine.airflow_api import AirflowError

            raise AirflowError("#AF.00000001.UNREACHABLE", "down", "start it")

    fake, clock = Broken(paused=False), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    with pytest.raises(Exception):
        svc.declare(_declare_req())
    assert not list(leases.root.glob("*.json"))


def test_renew_is_a_heartbeat_with_no_airflow_call(leases):
    fake, clock = FakeAirflow(paused=False), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    a = svc.declare(_declare_req())
    calls_before = len(fake.calls)
    clock.ns = 1_060 * NS
    r = svc.renew("hermes", a.activity_id, 3_000 * NS)
    assert len(fake.calls) == calls_before  # nothing asked of Airflow
    assert r.run_id == a.run_id and r.horizon_ns == 3_000 * NS and r.renewed_ns == 1_060 * NS and r.in_force
    lease = leases.read(a.activity_id)
    assert lease["heartbeat_ns"] == 1_060 * NS and lease["horizon_ns"] == 3_000 * NS
    # the read-back joins the run with the lease's current horizon
    assert svc.latest(a.activity_id).horizon_ns == 3_000 * NS
    with pytest.raises(act.ActivityError) as e:
        svc.renew("gaius", a.activity_id, 4_000 * NS)
    assert e.value.guru == act.GURU_NOTOWNER
    with pytest.raises(act.ActivityError) as e2:
        svc.renew("hermes", "00000000-0000-0000-0000-000000000000", 4_000 * NS)
    assert e2.value.guru == act.GURU_NOTFOUND


def test_release_flips_lease_touches_only_the_note_and_reads_released(leases):
    fake, clock = FakeAirflow(paused=False), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    a = svc.declare(_declare_req())
    clock.ns = 1_500 * NS
    r = svc.release("hermes", a.activity_id, "hangup")
    patches = [c for c in fake.calls if c[0] == "patch"]
    assert patches == [("patch", a.run_id, None, "released by hermes: hangup")]  # note only, never state
    assert fake.runs[a.run_id]["state"] == "running"  # Airflow decides when the sensor sees it
    assert r.state == engine_pb2.ACTIVITY_RELEASED and r.ended_ns == 1_500 * NS
    lease = leases.read(a.activity_id)
    assert lease["released"] is True and lease["outcome"] == "hangup" and lease["ended_ns"] == 1_500 * NS
    # the sensor observes → run success → RELEASED read from the lease
    fake.finish(a.run_id)
    got = svc.latest(a.activity_id)
    assert got.state == engine_pb2.ACTIVITY_RELEASED and not got.in_force and got.ended_ns == 1_500 * NS
    with pytest.raises(act.ActivityError) as e:
        svc.release("hermes", a.activity_id, "again")
    assert e.value.guru == act.GURU_ENDED
    with pytest.raises(act.ActivityError) as e2:
        svc.renew("hermes", a.activity_id, 9_000 * NS)
    assert e2.value.guru == act.GURU_ENDED


def test_state_mapping_expired_failed_queued_and_legacy_notes(leases):
    fake, clock = FakeAirflow(paused=False), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    a = svc.declare(_declare_req())
    # heartbeats stopped → the sensor sees lapsed → run success, lease not released → EXPIRED
    fake.finish(a.run_id)
    clock.ns = 1_400 * NS
    got = svc.latest(a.activity_id)
    assert got.state == engine_pb2.ACTIVITY_EXPIRED
    assert leases.read(a.activity_id)["ended_ns"]  # bookkeeping closed once
    assert leases.read(a.activity_id)["outcome"] == "expired"
    b = svc.declare(_declare_req(request_id="req-2"))
    fake.finish(b.run_id, "failed")
    assert svc.latest(b.activity_id).state == engine_pb2.ACTIVITY_FAILED
    fake.runs[b.run_id]["state"] = "queued"
    fake.runs[b.run_id]["end_date"] = None
    assert act.state_of_run(fake.runs[b.run_id], leases.read(b.activity_id)) == engine_pb2.ACTIVITY_QUEUED
    # legacy (pre-observe) runs without a lease still read their note
    legacy = {"state": "success", "note": "released by hermes: x", "conf": {"activity_id": "legacy"}}
    assert act.state_of_run(legacy, None) == engine_pb2.ACTIVITY_RELEASED
    legacy["note"] = "renewed → act-legacy-2"
    assert act.state_of_run(legacy, None) == engine_pb2.ACTIVITY_SUPERSEDED
    legacy["note"] = ""
    assert act.state_of_run(legacy, None) == engine_pb2.ACTIVITY_EXPIRED


def test_lease_state_alive_lapsed_released_and_control_view(leases):
    lease = {"activity_id": "a", "horizon_ns": 2_000 * NS, "heartbeat_ns": 1_000 * NS, "lease_ttl_s": 180, "released": False}
    assert act.lease_state(lease, 1_100 * NS) == act.LEASE_ALIVE
    assert act.lease_state(lease, 1_180 * NS) == act.LEASE_LAPSED  # TTL exactly reached
    assert act.lease_state(lease, 2_000 * NS) == act.LEASE_LAPSED  # horizon reached
    lease["released"] = True
    assert act.lease_state(lease, 1_050 * NS) == act.LEASE_RELEASED
    aid = "11111111-2222-3333-4444-555555555555"
    leases.write({**lease, "activity_id": aid, "released": False, "outcome": "", "kind": "interactive_session", "peer": "hermes", "owner": "o"})
    view = leases.view(aid, 1_050 * NS)
    assert view["state"] == "alive" and view["horizon_ns"] == 2_000 * NS and view["lease_ttl_s"] == 180 and view["kind"] == "interactive_session"
    assert [v["activity_id"] for v in leases.alive(1_050 * NS)] == [aid]
    assert leases.alive(1_200 * NS) == []
    assert leases.view("ffffffff-0000-0000-0000-000000000000", 1)["state"] == "unknown"
    with pytest.raises(act.ActivityError):
        leases.view("../etc/passwd", 1)


def test_watch_emits_on_change_and_heartbeat_and_drops_old_ended(leases):
    fake, clock = FakeAirflow(paused=False), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases, heartbeat_s=60, ended_window_s=600)
    a = svc.declare(_declare_req())
    ticks = {"n": 0}

    def active():
        # is_active is also consulted inside the sleep slices; the generator is
        # driven by next() below, so only guard against a runaway loop.
        ticks["n"] += 1
        return ticks["n"] <= 1000

    gen = svc.watch(is_active=active)
    recs, _ = next(gen)  # first emission: the in-force set
    assert [r.activity_id for r in recs] == [a.activity_id]
    clock.ns = 1_010 * NS  # nothing changed, inside heartbeat → no emission until change
    svc.release("hermes", a.activity_id, "hangup")
    fake.finish(a.run_id)
    recs, _ = next(gen)  # change: released
    assert recs[0].state == engine_pb2.ACTIVITY_RELEASED
    clock.ns = 1_080 * NS  # heartbeat elapsed → emits the same set again
    recs, _ = next(gen)
    assert len(recs) == 1
    clock.ns = 1_010 * NS + 700 * NS  # ended > 600 s ago → drops out
    recs, _ = next(gen)
    assert recs == []


def test_watch_event_proto_shape(leases):
    fake, clock = FakeAirflow(paused=False), Clock(1_000 * NS)
    svc = _svc(fake, clock, leases)
    a = svc.declare(_declare_req())
    ev = act.watch_event([a], 5)
    assert ev.observed_ns == 5 and ev.activities[0].activity_id == a.activity_id
    assert ev.activities[0].state == engine_pb2.ACTIVITY_RUNNING
