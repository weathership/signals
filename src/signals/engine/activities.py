"""Coordination Activities — inter-project intent with a lifetime, as runs of the
Signals-owned coordination DAGs in the shared Airflow, OBSERVED by Airflow.

Contract: zndx.engine.v1.Activity + zndx.scheduler.v1 Declare/Renew/Release/
List/WatchActivities (specification/protocol/coordination_activities.md).

Airflow's model for external work is a Sensor: the task is RUNNING because the
process is observed alive, not because someone said so. Signals therefore holds
a LEASE per activity (heartbeat, horizon, TTL, released flag) and the run's
``hold`` task is a deferrable ``SignalsActivitySensor`` whose trigger polls that
lease through the engine's control HTTP (``GET /coord/activities/<id>``,
bridged into the cluster as ``signals-engine-control``). Nobody patches a run's
STATE; Signals writes at most the run ``note`` for the UI.

  Declare  → write the lease (heartbeat = now) → trigger ONE run
             ``act-<activity_id>`` of the kind's DAG; conf = declaration +
             ``lease_url``.
  Renew    → heartbeat = now, horizon = request. No Airflow call, no new run.
  Release  → lease.released = true (+ outcome, ended). The trigger observes it,
             ``hold`` completes → run success → RELEASED.
  lapse    → heartbeats stop for the TTL, or the horizon passes: the trigger
             observes it → run success → EXPIRED.
  failed   → the run failed — intent NOT in force.

State read back = Airflow run state (truth even during the ≤ poll-interval
lag) with RELEASED vs EXPIRED decided by the lease.

Idempotency: ``activity_id = uuid5(NAMESPACE, "<peer>:<request_id>")`` so a
retried Declare maps to the same lease and run (Airflow 409 → existing run).

Topology reminder: only THIS engine talks to Airflow (``airflow_api``); peer
ENGINES call the RPCs; a peer's local processes ask their local engine.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from signals.engine.airflow_api import AirflowClient, AirflowError
from signals.engine.generated.zndx.engine.v1 import engine_pb2
from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2
from signals.engine.queue_share import ALLOWED_PEERS

log = logging.getLogger("signals.engine.activities")

# Generic coordination DAG; kinds with their own resource shape get their own
# DAG so the leaf claim can be expressed as an Airflow pool on the hold task.
DAG_ID = "coord_activity"
DAG_INTERACTIVE = "coord_interactive_session"
DAG_FOR_KIND = {"interactive_session": DAG_INTERACTIVE}
DAG_IDS = (DAG_ID, DAG_INTERACTIVE)
# Pool the interactive DAG's hold task occupies (slots = the agent-rtc leaf's
# guaranteed GPU tokens; include_deferred so a deferred hold still holds it).
POOL_FOR_DAG = {DAG_INTERACTIVE: ("agent_rtc", 1)}

# Fixed namespace for uuid5(peer:request_id) → activity_id. Never change.
NAMESPACE = uuid.UUID("6f5b3e2a-7c1d-4b8e-9a2f-0c4d5e6f7a8b")

GURU_UNKNOWNPEER = "#CO.00000001.UNKNOWNPEER"
GURU_NOTFOUND = "#CO.00000002.NOTFOUND"
GURU_HORIZON = "#CO.00000003.HORIZON"
GURU_ENDED = "#CO.00000004.ENDED"
GURU_BADREQUEST = "#CO.00000005.BADREQUEST"
GURU_NOTOWNER = "#CO.00000006.NOTOWNER"
GURU_LEASEIO = "#CO.00000007.LEASEIO"

RUN_PREFIX = "act-"

# Lease liveness: the declarer heartbeats well under this (Hermes: 60 s).
DEFAULT_LEASE_TTL_S = float(os.environ.get("SIGNALS_COORD_LEASE_TTL_S", "180"))
# What the Airflow triggerer can reach: the host bridge Service in the airflow
# namespace (config/k8s/airflow/host-bridge.yaml → socat → 127.0.0.1:50552).
DEFAULT_LEASE_URL_BASE = os.environ.get(
    "SIGNALS_COORD_LEASE_URL_BASE",
    "http://signals-engine-control.airflow.svc.cluster.local:50552",
)

# Lease states the control endpoint reports (and the trigger acts on).
LEASE_ALIVE = "alive"
LEASE_RELEASED = "released"
LEASE_LAPSED = "lapsed"

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


def run_id_for(activity_id: str) -> str:
    return f"{RUN_PREFIX}{activity_id}"


def dag_id_for(kind: str) -> str:
    return DAG_FOR_KIND.get(kind, DAG_ID)


# ── lease ────────────────────────────────────────────────────────────────────


def lease_state(lease: dict[str, Any], now_ns: int) -> str:
    """alive | released | lapsed — the one function the trigger's verdict rests on."""
    if lease.get("released"):
        return LEASE_RELEASED
    horizon = int(lease.get("horizon_ns") or 0)
    heartbeat = int(lease.get("heartbeat_ns") or 0)
    ttl_ns = int(float(lease.get("lease_ttl_s") or DEFAULT_LEASE_TTL_S) * 1_000_000_000)
    if now_ns >= horizon or (now_ns - heartbeat) >= ttl_ns:
        return LEASE_LAPSED
    return LEASE_ALIVE


class LeaseStore:
    """One JSON file per activity_id under ``root``; atomic replace on write.

    The lease is Signals' own record of the declarer's liveness — the thing the
    Airflow sensor observes. It is NOT the activity's state (Airflow's run is).
    """

    def __init__(self, root: Path, *, ttl_s: float = DEFAULT_LEASE_TTL_S):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_s = float(ttl_s)
        self._mu = threading.Lock()

    def path(self, activity_id: str) -> Path:
        safe = "".join(ch for ch in activity_id if ch.isalnum() or ch in "-_")
        if not safe or safe != activity_id:
            raise ActivityError(GURU_BADREQUEST, f"activity_id {activity_id!r} is not a uuid")
        return self.root / f"{safe}.json"

    def read(self, activity_id: str) -> dict[str, Any] | None:
        p = self.path(activity_id)
        try:
            return json.loads(p.read_text())
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as e:
            raise ActivityError(GURU_LEASEIO, f"lease {p} unreadable: {e!r}; Fix: inspect/remove the file") from e

    def write(self, lease: dict[str, Any]) -> dict[str, Any]:
        p = self.path(str(lease["activity_id"]))
        tmp = p.with_suffix(".json.tmp")
        with self._mu:
            try:
                tmp.write_text(json.dumps(lease, sort_keys=True))
                os.replace(tmp, p)
            except OSError as e:
                raise ActivityError(GURU_LEASEIO, f"lease {p} unwritable: {e!r}; Fix: check {self.root}") from e
        return lease

    def delete(self, activity_id: str) -> None:
        with self._mu:
            try:
                self.path(activity_id).unlink()
            except FileNotFoundError:
                pass

    def all(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.root.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, json.JSONDecodeError) as e:
                log.warning("lease %s unreadable: %r", p, e)
        return out

    def view(self, activity_id: str, now_ns: int) -> dict[str, Any]:
        """What the control endpoint serves: the lease + its computed state."""
        lease = self.read(activity_id)
        if lease is None:
            return {"activity_id": activity_id, "state": "unknown", "now_ns": now_ns}
        return {
            "activity_id": activity_id,
            "state": lease_state(lease, now_ns),
            "released": bool(lease.get("released")),
            "outcome": str(lease.get("outcome") or ""),
            "horizon_ns": int(lease.get("horizon_ns") or 0),
            "heartbeat_ns": int(lease.get("heartbeat_ns") or 0),
            "lease_ttl_s": float(lease.get("lease_ttl_s") or self.ttl_s),
            "kind": str(lease.get("kind") or ""),
            "peer": str(lease.get("peer") or ""),
            "owner": str(lease.get("owner") or ""),
            "now_ns": now_ns,
        }

    def alive(self, now_ns: int) -> list[dict[str, Any]]:
        return [self.view(str(l["activity_id"]), now_ns) for l in self.all() if lease_state(l, now_ns) == LEASE_ALIVE]


# ── records ──────────────────────────────────────────────────────────────────


def state_of_run(run: dict[str, Any], lease: dict[str, Any] | None) -> int:
    """Airflow run state (+ lease) → ActivityState.

    Legacy runs without a lease (pre-observe-model) still read their Signals
    note so history renders truthfully.
    """
    st = str(run.get("state") or "").lower()
    if st == "queued":
        return engine_pb2.ACTIVITY_QUEUED
    if st == "running":
        return engine_pb2.ACTIVITY_RUNNING
    if st == "success":
        if lease is not None:
            return engine_pb2.ACTIVITY_RELEASED if lease.get("released") else engine_pb2.ACTIVITY_EXPIRED
        note = str(run.get("note") or "")
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
    def from_run(cls, run: dict[str, Any], lease: dict[str, Any] | None = None) -> "ActivityRecord | None":
        conf = run.get("conf") or {}
        if not isinstance(conf, dict) or not conf.get("activity_id"):
            return None
        src: dict[str, Any] = dict(conf)
        if lease:
            src.update({k: v for k, v in lease.items() if k in ("horizon_ns", "renewed_ns", "ended_ns")})
        st = state_of_run(run, lease)
        ended = 0
        if st not in IN_FORCE:
            ended = int(src.get("ended_ns") or 0) or _iso_to_ns(run.get("end_date"))
        return cls(
            activity_id=str(conf["activity_id"]),
            kind=str(conf.get("kind") or ""),
            peer=str(conf.get("peer") or ""),
            owner=str(conf.get("owner") or ""),
            dag_id=str(run.get("dag_id") or DAG_ID),
            run_id=str(run.get("dag_run_id") or ""),
            request_id=str(conf.get("request_id") or ""),
            state=st,
            declared_ns=int(conf.get("declared_ns") or 0),
            horizon_ns=int(src.get("horizon_ns") or 0),
            renewed_ns=int(src.get("renewed_ns") or 0),
            ended_ns=ended,
            claims=[dict(c) for c in (conf.get("claims") or []) if isinstance(c, dict)],
            precludes=[str(p) for p in (conf.get("precludes") or [])],
            postures={str(k): str(v) for k, v in (conf.get("postures") or {}).items()},
            reason=str(conf.get("reason") or ""),
            note=str(run.get("note") or ""),
        )

    def conf(self, lease_url: str) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "request_id": self.request_id,
            "kind": self.kind,
            "peer": self.peer,
            "owner": self.owner,
            "declared_ns": self.declared_ns,
            "horizon_ns": self.horizon_ns,
            "horizon_iso": _ns_to_iso(self.horizon_ns),
            "lease_url": lease_url,
            "claims": list(self.claims),
            "precludes": list(self.precludes),
            "postures": dict(self.postures),
            "reason": self.reason,
        }

    def lease(self, *, heartbeat_ns: int, ttl_s: float) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "request_id": self.request_id,
            "kind": self.kind,
            "peer": self.peer,
            "owner": self.owner,
            "dag_id": self.dag_id,
            "run_id": self.run_id,
            "declared_ns": self.declared_ns,
            "horizon_ns": self.horizon_ns,
            "heartbeat_ns": heartbeat_ns,
            "renewed_ns": self.renewed_ns,
            "lease_ttl_s": float(ttl_s),
            "released": False,
            "outcome": "",
            "ended_ns": 0,
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


# ── service ──────────────────────────────────────────────────────────────────


class ActivityService:
    def __init__(
        self,
        airflow: AirflowClient,
        leases: LeaseStore,
        *,
        lease_url_base: str = DEFAULT_LEASE_URL_BASE,
        allowed_peers: frozenset[str] = ALLOWED_PEERS,
        poll_s: float = 5.0,
        heartbeat_s: float = 60.0,
        ended_window_s: float = 600.0,
        list_limit: int = 200,
        clock_ns: Callable[[], int] = _now_ns,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.airflow = airflow
        self.leases = leases
        self.lease_url_base = lease_url_base.rstrip("/")
        self.allowed_peers = allowed_peers
        self.poll_s = poll_s
        self.heartbeat_s = heartbeat_s
        self.ended_window_ns = int(ended_window_s * 1_000_000_000)
        self.list_limit = list_limit
        self._clock = clock_ns
        self._sleep = sleep
        self._ready_dags: set[str] = set()
        self._ready_pools: set[str] = set()

    # ── prerequisites ────────────────────────────────────────────────────────
    def lease_url(self, activity_id: str) -> str:
        return f"{self.lease_url_base}/coord/activities/{activity_id}"

    def _ensure_dag(self, dag_id: str) -> None:
        """The DAG must exist and be unpaused (new DAGs are paused at creation)."""
        if dag_id in self._ready_dags:
            return
        dag = self.airflow.get_dag(dag_id)  # DAGMISSING when absent
        if dag.get("is_paused"):
            log.info("activities: unpausing %s", dag_id)
            self.airflow.set_paused(dag_id, False)
        self._ready_dags.add(dag_id)

    def _ensure_pool(self, dag_id: str) -> None:
        """The hold task's pool must exist or Airflow never schedules it."""
        spec = POOL_FOR_DAG.get(dag_id)
        if spec is None or spec[0] in self._ready_pools:
            return
        name, slots = spec
        self.airflow.ensure_pool(
            name,
            slots=slots,
            include_deferred=True,
            description=f"coordination: {dag_id} hold — one slot per guaranteed GPU token on the leaf",
        )
        self._ready_pools.add(name)

    def _check_peer(self, peer: str) -> None:
        if peer not in self.allowed_peers:
            raise ActivityError(
                GURU_UNKNOWNPEER,
                f"peer {peer!r} is not an allowed peer {sorted(self.allowed_peers)}; "
                "Fix: add it to signals.engine.queue_share.ALLOWED_PEERS",
            )

    # ── reads ────────────────────────────────────────────────────────────────
    def _record(self, run: dict[str, Any]) -> ActivityRecord | None:
        conf = run.get("conf") or {}
        aid = str(conf.get("activity_id") or "") if isinstance(conf, dict) else ""
        lease = self.leases.read(aid) if aid else None
        rec = ActivityRecord.from_run(run, lease)
        if rec is None:
            return None
        # A run observed terminal closes the lease's bookkeeping once.
        if lease is not None and not rec.in_force and not int(lease.get("ended_ns") or 0):
            lease["ended_ns"] = rec.ended_ns or self._clock()
            if not lease.get("released"):
                lease["outcome"] = lease.get("outcome") or STATE_NAMES.get(rec.state, "")
            self.leases.write(lease)
            rec.ended_ns = int(lease["ended_ns"])
        return rec

    def _records(self) -> list[ActivityRecord]:
        recs: dict[str, ActivityRecord] = {}
        for dag_id in DAG_IDS:
            try:
                runs = self.airflow.list_dag_runs(dag_id, limit=self.list_limit, order_by="-run_after")
            except AirflowError as e:
                if e.guru == "#AF.00000003.DAGMISSING":
                    continue  # a DAG not yet deployed has no runs to read
                raise
            for run in runs:
                r = self._record(run)
                if r is None:
                    continue
                cur = recs.get(r.activity_id)
                if cur is None or r.declared_ns > cur.declared_ns:
                    recs[r.activity_id] = r
        return sorted(recs.values(), key=lambda r: r.declared_ns)

    def latest(self, activity_id: str) -> ActivityRecord | None:
        lease = self.leases.read(activity_id)
        if lease is not None:
            run = self.airflow.get_dag_run(str(lease["dag_id"]), str(lease["run_id"]))
            return self._record(run)
        for r in self._records():
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
        aid = activity_id_for(req.peer, req.request_id)
        dag_id = dag_id_for(req.kind)
        existing = self.leases.read(aid)
        if existing is not None:
            # Idempotent retry: the lease exists → the run exists (or Airflow
            # answers 409 below). Do not touch the heartbeat: a retry is not a renew.
            rec = self._record(self.airflow.get_dag_run(str(existing["dag_id"]), str(existing["run_id"])))
            if rec is not None:
                return rec
        self._ensure_dag(dag_id)
        self._ensure_pool(dag_id)
        rec = ActivityRecord(
            activity_id=aid,
            kind=req.kind,
            peer=req.peer,
            owner=req.owner,
            dag_id=dag_id,
            run_id=run_id_for(aid),
            request_id=req.request_id,
            state=engine_pb2.ACTIVITY_QUEUED,
            declared_ns=now,
            horizon_ns=int(req.horizon_ns),
            claims=[{"leaf": c.leaf, "gpu": int(c.gpu)} for c in req.claims],
            precludes=list(req.precludes),
            postures=dict(req.postures),
            reason=req.reason,
        )
        # Lease first: the sensor must find it the instant the run starts.
        self.leases.write(rec.lease(heartbeat_ns=now, ttl_s=self.leases.ttl_s))
        try:
            run = self.airflow.trigger_dag_run(dag_id, rec.run_id, rec.conf(self.lease_url(aid)))
        except AirflowError:
            self.leases.delete(aid)  # no run → no activity; never a lease without one
            raise
        got = self._record(run)
        if got is None:
            self.leases.delete(aid)
            raise ActivityError(GURU_BADREQUEST, f"Airflow answered a run without conf for {rec.run_id}")
        log.info(
            "activity declared %s kind=%s peer=%s owner=%s dag=%s run=%s state=%s horizon=%s ttl=%ss",
            aid, rec.kind, rec.peer, rec.owner, dag_id, got.run_id, STATE_NAMES.get(got.state),
            _ns_to_iso(rec.horizon_ns), self.leases.ttl_s,
        )
        return got

    def renew(self, peer: str, activity_id: str, horizon_ns: int) -> ActivityRecord:
        """Heartbeat + new horizon on the lease. No Airflow call."""
        self._check_peer(peer)
        lease = self.leases.read(activity_id)
        if lease is None:
            raise ActivityError(GURU_NOTFOUND, f"activity {activity_id} unknown")
        if str(lease.get("peer")) != peer:
            raise ActivityError(GURU_NOTOWNER, f"activity {activity_id} belongs to {lease.get('peer')!r}, not {peer!r}")
        if lease.get("released") or int(lease.get("ended_ns") or 0):
            raise ActivityError(
                GURU_ENDED, f"activity {activity_id} already ended ({lease.get('outcome') or 'ended'}); declare a new one"
            )
        now = self._clock()
        if int(horizon_ns) <= now:
            raise ActivityError(GURU_HORIZON, f"horizon_ns {int(horizon_ns)} is not in the future (now {now})")
        lease["heartbeat_ns"] = now
        lease["renewed_ns"] = now
        lease["horizon_ns"] = int(horizon_ns)
        self.leases.write(lease)
        rec = ActivityRecord(
            activity_id=activity_id,
            kind=str(lease.get("kind") or ""),
            peer=peer,
            owner=str(lease.get("owner") or ""),
            dag_id=str(lease.get("dag_id") or DAG_ID),
            run_id=str(lease.get("run_id") or run_id_for(activity_id)),
            request_id=str(lease.get("request_id") or ""),
            state=engine_pb2.ACTIVITY_RUNNING,
            declared_ns=int(lease.get("declared_ns") or 0),
            horizon_ns=int(horizon_ns),
            renewed_ns=now,
            claims=[dict(c) for c in (lease.get("claims") or []) if isinstance(c, dict)],
            precludes=[str(p) for p in (lease.get("precludes") or [])],
            postures={str(k): str(v) for k, v in (lease.get("postures") or {}).items()},
            reason=str(lease.get("reason") or ""),
        )
        log.debug("activity heartbeat %s horizon=%s", activity_id, _ns_to_iso(int(horizon_ns)))
        return rec

    def release(self, peer: str, activity_id: str, outcome: str) -> ActivityRecord:
        """Mark the lease released; the sensor observes it and the run completes."""
        self._check_peer(peer)
        lease = self.leases.read(activity_id)
        if lease is None:
            raise ActivityError(GURU_NOTFOUND, f"activity {activity_id} unknown")
        if str(lease.get("peer")) != peer:
            raise ActivityError(GURU_NOTOWNER, f"activity {activity_id} belongs to {lease.get('peer')!r}, not {peer!r}")
        if lease.get("released") or int(lease.get("ended_ns") or 0):
            raise ActivityError(GURU_ENDED, f"activity {activity_id} already ended ({lease.get('outcome') or 'ended'})")
        now = self._clock()
        lease["released"] = True
        lease["outcome"] = outcome or "released"
        lease["ended_ns"] = now
        self.leases.write(lease)
        note = f"released by {peer}: {outcome or 'released'}"
        # The UI note is a courtesy; the lease is the release. Never the state.
        try:
            self.airflow.patch_dag_run(str(lease["dag_id"]), str(lease["run_id"]), note=note)
        except AirflowError as e:
            log.warning("activity %s released; run note not written: %s", activity_id, e)
        rec = self.latest(activity_id)
        if rec is None:
            raise ActivityError(GURU_NOTFOUND, f"activity {activity_id} released but its run is gone")
        if rec.in_force:
            # The sensor has not observed the release yet (≤ poll interval):
            # report what the lease now guarantees will be read back.
            rec.state = engine_pb2.ACTIVITY_RELEASED
        rec.note = note
        rec.ended_ns = now
        log.info("activity released %s run=%s outcome=%s", activity_id, rec.run_id, outcome)
        return rec

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
