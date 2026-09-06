"""Coordination Activities — inter-project intent with a lifetime, as runs of the
Signals-owned ``coord_activity`` DAG in the shared Airflow.

Contract: zndx.engine.v1.Activity + zndx.scheduler.v1 Declare/Renew/Release/
List/WatchActivities (specification/protocol/coordination_activities.md).

Lifecycle at Signals (the Airflow run state is the truth peers read):
  Declare  → trigger run ``act-<activity_id>-1`` with the declaration as conf;
             its ``hold`` task waits (deferrable) until ``horizon_iso``.
  Renew    → trigger ``act-<activity_id>-<n+1>`` with the new horizon; PATCH
             the previous run success + note ``renewed → <run_id>`` (SUPERSEDED).
  Release  → PATCH the current run success + note ``released by <peer>: …``.
  horizon  → the run completes on its own → EXPIRED.
  failed   → FAILED — intent NOT in force.

Idempotency: ``activity_id = uuid5(NAMESPACE, "<peer>:<request_id>")`` so a
retried Declare maps to the same run (Airflow answers 409 → the existing run).

Topology reminder: only THIS engine talks to Airflow (``airflow_api``); peer
ENGINES call the RPCs; a peer's local processes ask their local engine.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from signals.engine.airflow_api import AirflowClient
from signals.engine.generated.zndx.engine.v1 import engine_pb2
from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2
from signals.engine.queue_share import ALLOWED_PEERS

log = logging.getLogger("signals.engine.activities")

DAG_ID = "coord_activity"
# Fixed namespace for uuid5(peer:request_id) → activity_id. Never change.
NAMESPACE = uuid.UUID("6f5b3e2a-7c1d-4b8e-9a2f-0c4d5e6f7a8b")

GURU_UNKNOWNPEER = "#CO.00000001.UNKNOWNPEER"
GURU_NOTFOUND = "#CO.00000002.NOTFOUND"
GURU_HORIZON = "#CO.00000003.HORIZON"
GURU_ENDED = "#CO.00000004.ENDED"
GURU_BADREQUEST = "#CO.00000005.BADREQUEST"
GURU_NOTOWNER = "#CO.00000006.NOTOWNER"

RUN_PREFIX = "act-"

# Proto state names (lowercase, minus the ACTIVITY_ prefix) — what peers log.
STATE_NAMES = {
    engine_pb2.ACTIVITY_STATE_UNSPECIFIED: "unspecified",
    engine_pb2.ACTIVITY_QUEUED: "queued",
    engine_pb2.ACTIVITY_RUNNING: "running",
    engine_pb2.ACTIVITY_RELEASED: "released",
    engine_pb2.ACTIVITY_EXPIRED: "expired",
    engine_pb2.ACTIVITY_FAILED: "failed",
    engine_pb2.ACTIVITY_SUPERSEDED: "superseded",
}
IN_FORCE = frozenset({engine_pb2.ACTIVITY_QUEUED, engine_pb2.ACTIVITY_RUNNING})


def _now_ns() -> int:
    return time.time_ns()


def _iso_to_ns(value: Any) -> int:
    if not value:
        return 0
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except ValueError:
        return 0


def _ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).isoformat()


def activity_id_for(peer: str, request_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{peer}:{request_id}"))


def run_id_for(activity_id: str, n: int) -> str:
    return f"{RUN_PREFIX}{activity_id}-{int(n)}"


def state_of_run(run: dict[str, Any]) -> int:
    """Airflow run state (+ Signals-written note) → ActivityState."""
    st = str(run.get("state") or "").lower()
    note = str(run.get("note") or "")
    if st == "queued":
        return engine_pb2.ACTIVITY_QUEUED
    if st == "running":
        return engine_pb2.ACTIVITY_RUNNING
    if st == "success":
        if note.startswith("released"):
            return engine_pb2.ACTIVITY_RELEASED
        if note.startswith("renewed"):
            return engine_pb2.ACTIVITY_SUPERSEDED
        return engine_pb2.ACTIVITY_EXPIRED
    if st == "failed":
        return engine_pb2.ACTIVITY_FAILED
    return engine_pb2.ACTIVITY_STATE_UNSPECIFIED


@dataclass
class ActivityRecord:
    activity_id: str
    kind: str
    peer: str
    owner: str
    dag_id: str
    run_id: str
    n: int
    request_id: str
    state: int
    declared_ns: int
    horizon_ns: int
    renewed_ns: int = 0
    ended_ns: int = 0
    claims: list[dict[str, Any]] = field(default_factory=list)
    precludes: list[str] = field(default_factory=list)
    postures: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    note: str = ""

    @property
    def in_force(self) -> bool:
        return self.state in IN_FORCE

    @classmethod
    def from_run(cls, run: dict[str, Any]) -> "ActivityRecord | None":
        conf = run.get("conf") or {}
        if not isinstance(conf, dict) or not conf.get("activity_id"):
            return None
        st = state_of_run(run)
        ended = 0 if st in IN_FORCE else _iso_to_ns(run.get("end_date"))
        return cls(
            activity_id=str(conf["activity_id"]),
            kind=str(conf.get("kind") or ""),
            peer=str(conf.get("peer") or ""),
            owner=str(conf.get("owner") or ""),
            dag_id=str(run.get("dag_id") or DAG_ID),
            run_id=str(run.get("dag_run_id") or ""),
            n=int(conf.get("n") or 1),
            request_id=str(conf.get("request_id") or ""),
            state=st,
            declared_ns=int(conf.get("declared_ns") or 0),
            horizon_ns=int(conf.get("horizon_ns") or 0),
            renewed_ns=int(conf.get("renewed_ns") or 0),
            ended_ns=ended,
            claims=[dict(c) for c in (conf.get("claims") or []) if isinstance(c, dict)],
            precludes=[str(p) for p in (conf.get("precludes") or [])],
            postures={str(k): str(v) for k, v in (conf.get("postures") or {}).items()},
            reason=str(conf.get("reason") or ""),
            note=str(run.get("note") or ""),
        )

    def conf(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "n": self.n,
            "request_id": self.request_id,
            "kind": self.kind,
            "peer": self.peer,
            "owner": self.owner,
            "declared_ns": self.declared_ns,
            "renewed_ns": self.renewed_ns,
            "horizon_ns": self.horizon_ns,
            "horizon_iso": _ns_to_iso(self.horizon_ns),
            "claims": list(self.claims),
            "precludes": list(self.precludes),
            "postures": dict(self.postures),
            "reason": self.reason,
        }

    def to_proto(self) -> engine_pb2.Activity:
        a = engine_pb2.Activity(
            activity_id=self.activity_id,
            kind=self.kind,
            peer=self.peer,
            owner=self.owner,
            dag_id=self.dag_id,
            run_id=self.run_id,
            state=self.state,
            declared_ns=self.declared_ns,
            horizon_ns=self.horizon_ns,
            renewed_ns=self.renewed_ns,
            ended_ns=self.ended_ns,
            reason=self.reason,
            note=self.note,
        )
        for c in self.claims:
            a.claims.append(
                engine_pb2.ActivityClaim(leaf=str(c.get("leaf") or ""), gpu=int(c.get("gpu") or 0))
            )
        a.precludes.extend(self.precludes)
        for k, v in self.postures.items():
            a.postures[k] = v
        return a


class ActivityError(Exception):
    """Refusal the servicer reports in-band (accepted=false + error)."""

    def __init__(self, guru: str, msg: str):
        self.guru = guru
        super().__init__(f"{guru} {msg}")


class ActivityService:
    def __init__(
        self,
        airflow: AirflowClient,
        *,
        dag_id: str = DAG_ID,
        allowed_peers: frozenset[str] = ALLOWED_PEERS,
        poll_s: float = 5.0,
        heartbeat_s: float = 60.0,
        ended_window_s: float = 600.0,
        list_limit: int = 200,
        clock_ns: Callable[[], int] = _now_ns,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.airflow = airflow
        self.dag_id = dag_id
        self.allowed_peers = allowed_peers
        self.poll_s = poll_s
        self.heartbeat_s = heartbeat_s
        self.ended_window_ns = int(ended_window_s * 1_000_000_000)
        self.list_limit = list_limit
        self._clock = clock_ns
        self._sleep = sleep
        self._unpaused = False

    # ── prerequisites ────────────────────────────────────────────────────────
    def _ensure_dag(self) -> None:
        """The DAG must exist and be unpaused (new DAGs are paused at creation)."""
        if self._unpaused:
            return
        dag = self.airflow.get_dag(self.dag_id)  # DAGMISSING when absent
        if dag.get("is_paused"):
            log.info("activities: unpausing %s", self.dag_id)
            self.airflow.set_paused(self.dag_id, False)
        self._unpaused = True

    def _check_peer(self, peer: str) -> None:
        if peer not in self.allowed_peers:
            raise ActivityError(
                GURU_UNKNOWNPEER,
                f"peer {peer!r} is not an allowed peer {sorted(self.allowed_peers)}; "
                "Fix: add it to signals.engine.queue_share.ALLOWED_PEERS",
            )

    # ── reads ────────────────────────────────────────────────────────────────
    def _records(self, *, run_id_pattern: str | None = None) -> list[ActivityRecord]:
        runs = self.airflow.list_dag_runs(
            self.dag_id, limit=self.list_limit, order_by="-run_after", run_id_pattern=run_id_pattern
        )
        recs = [r for r in (ActivityRecord.from_run(x) for x in runs) if r is not None]
        latest: dict[str, ActivityRecord] = {}
        for r in recs:
            cur = latest.get(r.activity_id)
            if cur is None or r.n > cur.n:
                latest[r.activity_id] = r
        return sorted(latest.values(), key=lambda r: r.declared_ns)

    def latest(self, activity_id: str) -> ActivityRecord | None:
        recs = self._records(run_id_pattern=f"{RUN_PREFIX}{activity_id}-")
        for r in recs:
            if r.activity_id == activity_id:
                return r
        return None

    def list(
        self,
        *,
        peer: str = "",
        kind: str = "",
        active_only: bool = False,
        since_ns: int = 0,
        limit: int = 0,
    ) -> list[ActivityRecord]:
        out = []
        for r in self._records():
            if peer and r.peer != peer:
                continue
            if kind and r.kind != kind:
                continue
            if active_only and not r.in_force:
                continue
            if since_ns and max(r.declared_ns, r.renewed_ns, r.ended_ns) < since_ns:
                continue
            out.append(r)
        if limit:
            out = out[-limit:]
        return out

    def in_force_plus_recent(self, now_ns: int | None = None) -> list[ActivityRecord]:
        now = now_ns if now_ns is not None else self._clock()
        out = []
        for r in self._records():
            if r.in_force or (r.ended_ns and now - r.ended_ns <= self.ended_window_ns):
                out.append(r)
        return out

    # ── writes ───────────────────────────────────────────────────────────────
    def declare(self, req: scheduler_pb2.DeclareActivityRequest) -> ActivityRecord:
        self._check_peer(req.peer)
        if not req.request_id or not req.kind:
            raise ActivityError(GURU_BADREQUEST, "request_id and kind are required")
        now = self._clock()
        if int(req.horizon_ns) <= now:
            raise ActivityError(
                GURU_HORIZON, f"horizon_ns {int(req.horizon_ns)} is not in the future (now {now})"
            )
        self._ensure_dag()
        aid = activity_id_for(req.peer, req.request_id)
        rec = ActivityRecord(
            activity_id=aid,
            kind=req.kind,
            peer=req.peer,
            owner=req.owner,
            dag_id=self.dag_id,
            run_id=run_id_for(aid, 1),
            n=1,
            request_id=req.request_id,
            state=engine_pb2.ACTIVITY_QUEUED,
            declared_ns=now,
            horizon_ns=int(req.horizon_ns),
            claims=[{"leaf": c.leaf, "gpu": int(c.gpu)} for c in req.claims],
            precludes=list(req.precludes),
            postures=dict(req.postures),
            reason=req.reason,
        )
        run = self.airflow.trigger_dag_run(self.dag_id, rec.run_id, rec.conf())
        got = ActivityRecord.from_run(run)
        if got is None:
            raise ActivityError(GURU_BADREQUEST, f"Airflow answered a run without conf for {rec.run_id}")
        log.info(
            "activity declared %s kind=%s peer=%s owner=%s run=%s state=%s horizon=%s",
            aid, rec.kind, rec.peer, rec.owner, got.run_id, STATE_NAMES.get(got.state), _ns_to_iso(rec.horizon_ns),
        )
        return got

    def renew(self, peer: str, activity_id: str, horizon_ns: int) -> ActivityRecord:
        self._check_peer(peer)
        cur = self.latest(activity_id)
        if cur is None:
            raise ActivityError(GURU_NOTFOUND, f"activity {activity_id} unknown")
        if cur.peer != peer:
            raise ActivityError(GURU_NOTOWNER, f"activity {activity_id} belongs to {cur.peer!r}, not {peer!r}")
        if not cur.in_force:
            raise ActivityError(
                GURU_ENDED, f"activity {activity_id} is {STATE_NAMES.get(cur.state)}; declare a new one"
            )
        now = self._clock()
        if int(horizon_ns) <= now:
            raise ActivityError(GURU_HORIZON, f"horizon_ns {int(horizon_ns)} is not in the future (now {now})")
        nxt = ActivityRecord(**{**cur.__dict__})
        nxt.n = cur.n + 1
        nxt.run_id = run_id_for(activity_id, nxt.n)
        nxt.horizon_ns = int(horizon_ns)
        nxt.renewed_ns = now
        nxt.state = engine_pb2.ACTIVITY_QUEUED
        nxt.ended_ns = 0
        nxt.note = ""
        run = self.airflow.trigger_dag_run(self.dag_id, nxt.run_id, nxt.conf())
        # Supersede the previous run only after the new one exists: the intent
        # never has a gap while renewing.
        self.airflow.patch_dag_run(
            self.dag_id, cur.run_id, state="success", note=f"renewed → {nxt.run_id}"
        )
        got = ActivityRecord.from_run(run) or nxt
        log.info("activity renewed %s run=%s horizon=%s", activity_id, got.run_id, _ns_to_iso(nxt.horizon_ns))
        return got

    def release(self, peer: str, activity_id: str, outcome: str) -> ActivityRecord:
        self._check_peer(peer)
        cur = self.latest(activity_id)
        if cur is None:
            raise ActivityError(GURU_NOTFOUND, f"activity {activity_id} unknown")
        if cur.peer != peer:
            raise ActivityError(GURU_NOTOWNER, f"activity {activity_id} belongs to {cur.peer!r}, not {peer!r}")
        if not cur.in_force:
            raise ActivityError(GURU_ENDED, f"activity {activity_id} already {STATE_NAMES.get(cur.state)}")
        note = f"released by {peer}: {outcome or 'released'}"
        run = self.airflow.patch_dag_run(self.dag_id, cur.run_id, state="success", note=note)
        got = ActivityRecord.from_run(run)
        if got is None:
            got = cur
            got.state = engine_pb2.ACTIVITY_RELEASED
            got.note = note
            got.ended_ns = self._clock()
        if not got.ended_ns:
            got.ended_ns = self._clock()
        log.info("activity released %s run=%s outcome=%s", activity_id, cur.run_id, outcome)
        return got

    # ── watch ────────────────────────────────────────────────────────────────
    def watch(self, *, is_active: Callable[[], bool] = lambda: True) -> Iterator[tuple[list[ActivityRecord], int]]:
        """Yield (records, observed_ns) on change and at least every heartbeat."""
        last_sig: tuple | None = None
        last_emit_ns = 0
        while is_active():
            now = self._clock()
            recs = self.in_force_plus_recent(now)
            sig = tuple(sorted((r.activity_id, r.run_id, r.state, r.horizon_ns, r.note) for r in recs))
            if sig != last_sig or (now - last_emit_ns) >= int(self.heartbeat_s * 1_000_000_000):
                yield recs, now
                last_sig = sig
                last_emit_ns = now
            # Sleep in short slices so a client disconnect is noticed promptly.
            remaining = self.poll_s
            while remaining > 0 and is_active():
                step = min(1.0, remaining)
                self._sleep(step)
                remaining -= step


def watch_event(recs: list[ActivityRecord], observed_ns: int) -> scheduler_pb2.ActivityWatchEvent:
    ev = scheduler_pb2.ActivityWatchEvent(observed_ns=observed_ns)
    for r in recs:
        ev.activities.append(r.to_proto())
    return ev
