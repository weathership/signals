"""coord_signals — Airflow sensor + trigger that OBSERVE a Coordination Activity.

Airflow's model for external work is a Sensor: the ``hold`` task is RUNNING
because the external process (an agent-rtc session, a curation window, …) is
observed alive, not because someone patched the run. The Signals engine holds
a lease per activity (heartbeat, horizon, TTL, released flag) and serves it on
its control HTTP; ``SignalsLeaseTrigger`` polls that view from the triggerer
(no worker slot while waiting) and fires with the outcome; the sensor's
``execute_complete`` returns it as the task's XCom for ``close``.

Mounted into /opt/airflow/plugins (on sys.path in every Airflow component,
including the triggerer, which imports trigger classes by classpath).

Nobody outside Signals talks to Airflow; nobody in Airflow talks to a peer.
The lease URL is Signals-internal topology carried in the run conf.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Asset, BaseOperator
from airflow.sdk.bases.sensor import BaseSensorOperator, PokeReturnValue
from airflow.triggers.base import BaseTrigger, TriggerEvent

import coord_lease

log = logging.getLogger("coord_signals")

GURU_BADEVENT = "#CO.00000008.BADEVENT"
GURU_DECLAREHTTP = "#CO.0000000A.DECLAREHTTP"

ACTIVITY_STARTED = Asset("zndx.coord.activity")
ACTIVITY_ENDED = Asset("zndx.coord.activity.ended")

DEFAULT_POLL_S = 5.0
DEFAULT_HOLD_TIMEOUT = timedelta(hours=24)  # outer net only; the lease decides

# The Signals engine's control HTTP as the cluster reaches it (host bridge
# Service in the airflow namespace → socat → 127.0.0.1:50552). Signals-internal
# topology: a peer never holds this; Airflow talks to Signals and to nobody else.
SIGNALS_CONTROL_BASE = "http://signals-engine-control.airflow.svc.cluster.local:50552"


def ended_asset_for(kind: str) -> Asset:
    """Per-kind end Asset — what the NEXT workload's DAG schedules on."""
    return Asset(f"zndx.coord.{kind}.ended")


class SignalsLeaseTrigger(BaseTrigger):
    """Runs in the triggerer: poll the lease until it is released or lapsed."""

    def __init__(
        self,
        activity_id: str,
        lease_url: str,
        poll_s: float = DEFAULT_POLL_S,
        unreachable_log_every_s: float = 60.0,
    ):
        super().__init__()
        self.activity_id = activity_id
        self.lease_url = lease_url
        self.poll_s = float(poll_s)
        self.unreachable_log_every_s = float(unreachable_log_every_s)

    def serialize(self) -> tuple[str, dict[str, Any]]:
        return (
            "coord_signals.SignalsLeaseTrigger",
            {
                "activity_id": self.activity_id,
                "lease_url": self.lease_url,
                "poll_s": self.poll_s,
                "unreachable_log_every_s": self.unreachable_log_every_s,
            },
        )

    async def run(self) -> AsyncIterator[TriggerEvent]:
        last_note = 0.0
        polls = 0
        while True:
            polls += 1
            try:
                state, payload = await asyncio.to_thread(coord_lease.poll, self.lease_url, 5.0)
            except coord_lease.LeaseUnreachable as e:
                now = time.monotonic()
                if now - last_note >= self.unreachable_log_every_s:
                    self.log.warning(
                        "activity %s: lease %s unreachable (%s) — a dark Signals is not a lapse; waiting",
                        self.activity_id, self.lease_url, e,
                    )
                    last_note = now
                await asyncio.sleep(self.poll_s)
                continue
            outcome = coord_lease.outcome_for(state)
            if outcome is not None:
                self.log.info(
                    "activity %s: lease %s after %d polls (%s)", self.activity_id, outcome, polls,
                    payload.get("outcome") or "",
                )
                yield TriggerEvent(
                    {
                        "outcome": outcome,
                        "activity_id": self.activity_id,
                        "lease": payload,
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                return
            if state == coord_lease.UNKNOWN:
                now = time.monotonic()
                if now - last_note >= self.unreachable_log_every_s:
                    self.log.warning(
                        "activity %s: Signals has no lease at %s (unknown) — waiting", self.activity_id, self.lease_url
                    )
                    last_note = now
            await asyncio.sleep(self.poll_s)


class SignalsActivitySensor(BaseSensorOperator):
    """The activity's ``hold``: RUNNING while the lease is alive.

    Deferrable (default): hands the wait to ``SignalsLeaseTrigger`` and holds
    no worker slot. Non-deferrable: ``poke`` reads the same lease in
    ``mode="reschedule"``. Either way the task's return value (XCom) is the
    outcome — ``released`` or ``lapsed`` — which ``close`` reads.
    """

    template_fields = ("activity_id", "lease_url")
    ui_color = "#b5e0f5"

    def __init__(
        self,
        *,
        activity_id: str,
        lease_url: str,
        poll_s: float = DEFAULT_POLL_S,
        deferrable: bool = True,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.activity_id = activity_id
        self.lease_url = lease_url
        self.poll_s = float(poll_s)
        self.deferrable = bool(deferrable)

    def poke(self, context: Any) -> bool | PokeReturnValue:
        try:
            state, payload = coord_lease.poll(self.lease_url, 5.0)
        except coord_lease.LeaseUnreachable as e:
            self.log.warning("activity %s: lease unreachable (%s) — waiting", self.activity_id, e)
            return False
        outcome = coord_lease.outcome_for(state)
        if outcome is None:
            return False
        self.log.info("activity %s: lease %s (%s)", self.activity_id, outcome, payload.get("outcome") or "")
        return PokeReturnValue(is_done=True, xcom_value=outcome)

    def execute(self, context: Any) -> Any:
        if not self.deferrable:
            return super().execute(context)
        self.log.info(
            "activity %s: observing lease %s every %ss (outer net %ss)",
            self.activity_id, self.lease_url, self.poll_s, self.timeout,
        )
        self.defer(
            trigger=SignalsLeaseTrigger(
                activity_id=self.activity_id, lease_url=self.lease_url, poll_s=self.poll_s
            ),
            method_name="execute_complete",
            timeout=timedelta(seconds=float(self.timeout)),
        )

    def execute_complete(self, context: Any, event: dict[str, Any] | None = None) -> str:
        if not isinstance(event, dict) or event.get("outcome") not in coord_lease.TERMINAL:
            raise AirflowException(
                f"{GURU_BADEVENT} SignalsLeaseTrigger for activity {self.activity_id} returned a "
                f"malformed event: {event!r}\n  Try: kubectl -n airflow logs deploy/airflow-triggerer"
            )
        outcome = str(event["outcome"])
        self.log.info("activity %s: hold ends — %s", self.activity_id, outcome)
        return outcome


class SignalsDeclareOperator(BaseOperator):
    """A scheduled run declares ITSELF as a Coordination Activity.

    The run IS the activity: this task POSTs the declaration — kind, peer,
    owner, claims (the workload's YuniKorn queue configuration), precludes,
    postures, horizon, reason — with its own dag_id/run_id/task_id to the
    Signals engine's control HTTP. Signals writes the lease, asserts the claims
    into its queue-share arbiter (the "next workload indicates to the arbiter
    that it must assert the new configuration"), and answers the lease view.
    ``activity_id`` and ``lease_url`` go to XCom for the ``hold`` sensor.

    The owner ENGINE (peer) sees its own activity in force on
    ``Scheduler/WatchActivities``, starts the workload, heartbeats the lease and
    releases it when done; a lease nobody heartbeats lapses and the run ends
    EXPIRED with its configuration retired. Nobody outside Signals is called.
    """

    ui_color = "#ffe8a8"

    def __init__(
        self,
        *,
        kind: str,
        peer: str,
        claims: list[dict[str, Any]] | None = None,
        horizon_s: float,
        reason: str = "",
        owner: str | None = None,
        precludes: list[str] | None = None,
        postures: dict[str, str] | None = None,
        control_base: str = SIGNALS_CONTROL_BASE,
        timeout_s: float = 15.0,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.kind = kind
        self.peer = peer
        self.claims = [dict(c) for c in (claims or [])]
        self.horizon_s = float(horizon_s)
        self.reason = reason
        self.activity_owner = owner
        self.precludes = list(precludes or [])
        self.postures = dict(postures or {})
        self.control_base = control_base.rstrip("/")
        self.timeout_s = float(timeout_s)

    def execute(self, context: Any) -> dict[str, Any]:
        dag_run = context["dag_run"]
        ti = context["ti"]
        dag_id = str(getattr(dag_run, "dag_id", None) or context["dag"].dag_id)
        run_id = str(getattr(dag_run, "run_id", None) or context.get("run_id") or "")
        task_id = str(getattr(ti, "task_id", None) or self.task_id)
        payload = {
            "kind": self.kind,
            "peer": self.peer,
            "owner": self.activity_owner or f"{dag_id}/{run_id}",
            "claims": self.claims,
            "precludes": self.precludes,
            "postures": self.postures,
            "horizon_s": self.horizon_s,
            "reason": self.reason,
            "dag_id": dag_id,
            "run_id": run_id,
            "task_id": task_id,
        }
        url = f"{self.control_base}/coord/activities"
        self.log.info("declaring %s/%s as activity kind=%s peer=%s claims=%s → %s", dag_id, run_id, self.kind, self.peer, self.claims, url)
        try:
            view = coord_lease.post_json(url, payload, self.timeout_s)
        except coord_lease.DeclareRefused as e:
            raise AirflowException(
                f"{GURU_DECLAREHTTP} Signals refused the declaration of {dag_id}/{run_id} ({e})\n"
                "  Try: the guru in the body names the cause (peer allowlist, claims vs leaf max, horizon)"
            ) from e
        except coord_lease.LeaseUnreachable as e:
            raise AirflowException(
                f"{GURU_DECLAREHTTP} Signals control HTTP unreachable at {url}: {e}\n"
                "  Try: kubectl -n airflow get deploy signals-engine-control-proxy; the signals-engine process"
            ) from e
        activity_id = str(view.get("activity_id") or "")
        lease_url = str(view.get("lease_url") or "")
        if not activity_id or not lease_url:
            raise AirflowException(f"{GURU_DECLAREHTTP} Signals answered without activity_id/lease_url: {view!r}")
        ti.xcom_push(key="activity_id", value=activity_id)
        ti.xcom_push(key="lease_url", value=lease_url)
        self.log.info(
            "activity %s declared: state=%s lease=%s note=%r",
            activity_id, view.get("activity_state"), lease_url, view.get("note") or "",
        )
        return view


def _declare(**context: Any) -> str:
    conf = dict(context["dag_run"].conf or {})
    print(
        f"coord declare: activity={conf.get('activity_id')} kind={conf.get('kind')} "
        f"peer={conf.get('peer')} owner={conf.get('owner')} horizon={conf.get('horizon_iso')} "
        f"claims={conf.get('claims')} precludes={conf.get('precludes')} postures={conf.get('postures')} "
        f"reason={conf.get('reason')!r} lease={conf.get('lease_url')}"
    )
    return str(conf.get("activity_id") or "")


def _close(**context: Any) -> str:
    conf = dict(context["dag_run"].conf or {})
    outcome = context["ti"].xcom_pull(task_ids="hold")
    if outcome not in coord_lease.TERMINAL:
        raise AirflowException(
            f"{GURU_BADEVENT} hold returned {outcome!r} for activity {conf.get('activity_id')}"
        )
    print(
        f"coord close: activity={conf.get('activity_id')} kind={conf.get('kind')} peer={conf.get('peer')} "
        f"outcome={outcome} ({'owner released it' if outcome == 'released' else 'heartbeats stopped or horizon passed'})"
    )
    return str(outcome)


def make_coord_dag(
    dag_id: str,
    *,
    description: str,
    pool: str | None = None,
    hold_timeout: timedelta = DEFAULT_HOLD_TIMEOUT,
    poll_s: float = DEFAULT_POLL_S,
) -> DAG:
    """declare → hold (observe the lease) → close. ``pool`` expresses the leaf
    claim in Airflow's own vocabulary (agent_rtc: one slot per guaranteed GPU
    token; include_deferred so the deferred hold still occupies it)."""
    default_args = {
        "owner": "signals",
        "depends_on_past": False,
        "email_on_failure": False,
        "email_on_retry": False,
        "retries": 0,
        "retry_delay": timedelta(minutes=1),
    }
    with DAG(
        dag_id=dag_id,
        description=description,
        default_args=default_args,
        schedule=None,
        start_date=datetime(2026, 1, 1),
        catchup=False,
        is_paused_upon_creation=False,
        tags=["coordination", "federation", "signals"],
        max_active_runs=32,
    ) as dag:
        declare = PythonOperator(task_id="declare", python_callable=_declare, outlets=[ACTIVITY_STARTED])
        hold_kwargs: dict[str, Any] = dict(
            task_id="hold",
            activity_id="{{ dag_run.conf['activity_id'] }}",
            lease_url="{{ dag_run.conf['lease_url'] }}",
            poll_s=poll_s,
            deferrable=True,
            timeout=hold_timeout.total_seconds(),
            mode="reschedule",
            poke_interval=poll_s,
        )
        if pool:
            hold_kwargs["pool"] = pool
        hold = SignalsActivitySensor(**hold_kwargs)
        close = PythonOperator(task_id="close", python_callable=_close, outlets=[ACTIVITY_ENDED])
        declare >> hold >> close
    return dag


# ── ordered workloads: the run IS the activity ───────────────────────────────


def _close_workload(hold_task_id: str, kind: str, **context: Any) -> str:
    outcome = context["ti"].xcom_pull(task_ids=hold_task_id)
    if outcome not in coord_lease.TERMINAL:
        raise AirflowException(f"{GURU_BADEVENT} {hold_task_id} returned {outcome!r} for workload {kind}")
    print(
        f"workload close: kind={kind} outcome={outcome} "
        f"({'owner released it' if outcome == 'released' else 'heartbeats stopped or horizon passed'}) — "
        f"queue configuration retired at Signals; Asset zndx.coord.{kind}.ended emitted"
    )
    return str(outcome)


def _workload_tasks(
    *,
    name: str,
    kind: str,
    peer: str,
    claims: list[dict[str, Any]],
    horizon_s: float,
    reason: str,
    precludes: list[str] | None,
    postures: dict[str, str] | None,
    owner: str | None,
    pool: str | None,
    poll_s: float,
    suffix: str,
) -> tuple[BaseOperator, BaseOperator, BaseOperator]:
    declare_id, hold_id, close_id = f"declare{suffix}", f"hold{suffix}", f"close{suffix}"
    declare = SignalsDeclareOperator(
        task_id=declare_id,
        kind=kind,
        peer=peer,
        claims=claims,
        horizon_s=horizon_s,
        reason=reason,
        precludes=precludes,
        postures=postures,
        owner=owner,
        outlets=[ACTIVITY_STARTED],
    )
    hold_kwargs: dict[str, Any] = dict(
        task_id=hold_id,
        activity_id="{{ ti.xcom_pull(task_ids='" + declare_id + "', key='activity_id') }}",
        lease_url="{{ ti.xcom_pull(task_ids='" + declare_id + "', key='lease_url') }}",
        poll_s=poll_s,
        deferrable=True,
        # The lease's own horizon is the workload's bound; the sensor timeout is
        # only the outer net beyond it (a dark Signals is not a lapse).
        timeout=float(horizon_s) + 3600.0,
        mode="reschedule",
        poke_interval=poll_s,
    )
    if pool:
        hold_kwargs["pool"] = pool
    hold = SignalsActivitySensor(**hold_kwargs)
    close = PythonOperator(
        task_id=close_id,
        python_callable=_close_workload,
        op_kwargs={"hold_task_id": hold_id, "kind": kind},
        outlets=[ACTIVITY_ENDED, ended_asset_for(kind)],
    )
    declare >> hold >> close
    return declare, hold, close


def make_workload_dag(
    dag_id: str,
    *,
    kind: str,
    peer: str,
    claims: list[dict[str, Any]],
    horizon_s: float,
    schedule: Any,
    reason: str,
    precludes: list[str] | None = None,
    postures: dict[str, str] | None = None,
    owner: str | None = None,
    pool: str | None = None,
    tags: list[str] | None = None,
    description: str | None = None,
    start_date: datetime = datetime(2026, 1, 1),
    catchup: bool = False,
    poll_s: float = DEFAULT_POLL_S,
    paused: bool = False,
) -> DAG:
    """ONE scheduled workload as an activity: declare (the run declares itself;
    its claims are its YuniKorn queue configuration, asserted at Signals) →
    hold (observe the lease the owner engine heartbeats) → close (emit
    ``zndx.coord.<kind>.ended`` so the next workload can schedule on it).

    ``schedule`` is a cron string, a timedelta, an Asset (or list) — the last is
    how "when one workload completes, the next runs" is expressed in Airflow.
    ``paused`` = born paused (a catalogued workload that has not migrated yet:
    visible in Airflow, never scheduled until the catalogue enables it).
    """
    default_args = {
        "owner": "signals",
        "depends_on_past": False,
        "email_on_failure": False,
        "email_on_retry": False,
        "retries": 0,
        "retry_delay": timedelta(minutes=1),
    }
    with DAG(
        dag_id=dag_id,
        description=description or f"Workload {kind} ({peer}) as a Coordination Activity — claims are its YK queue config",
        default_args=default_args,
        schedule=schedule,
        start_date=start_date,
        catchup=catchup,
        is_paused_upon_creation=bool(paused),
        tags=list(tags or ["coordination", "workload", peer]),
        max_active_runs=1,
    ) as dag:
        _workload_tasks(
            name=kind, kind=kind, peer=peer, claims=claims, horizon_s=horizon_s, reason=reason,
            precludes=precludes, postures=postures, owner=owner, pool=pool, poll_s=poll_s, suffix="",
        )
    return dag


def make_chain_dag(
    dag_id: str,
    workloads: list[dict[str, Any]],
    *,
    schedule: Any,
    tags: list[str] | None = None,
    description: str | None = None,
    start_date: datetime = datetime(2026, 1, 1),
    catchup: bool = False,
    poll_s: float = DEFAULT_POLL_S,
) -> DAG:
    """Several workloads ORDERED in one run: declare_a → hold_a → close_a →
    declare_b → hold_b → close_b … Each declare asserts that workload's queue
    configuration at Signals; each close (the previous workload's end) is what
    lets the next declare run — "when one workload is completed then the next
    scheduled workload indicates to the arbiter that it must assert the new
    configuration". Each workload dict: name, kind, peer, claims, horizon_s,
    reason, optional precludes/postures/owner/pool.
    """
    if not workloads:
        raise ValueError(f"{dag_id}: a chain needs at least one workload")
    default_args = {
        "owner": "signals",
        "depends_on_past": False,
        "email_on_failure": False,
        "email_on_retry": False,
        "retries": 0,
        "retry_delay": timedelta(minutes=1),
    }
    with DAG(
        dag_id=dag_id,
        description=description or f"Ordered workloads: {' → '.join(str(w.get('name') or w['kind']) for w in workloads)}",
        default_args=default_args,
        schedule=schedule,
        start_date=start_date,
        catchup=catchup,
        is_paused_upon_creation=False,
        tags=list(tags or ["coordination", "workload", "chain"]),
        max_active_runs=1,
    ) as dag:
        prev_close: BaseOperator | None = None
        for w in workloads:
            name = str(w.get("name") or w["kind"])
            declare, _hold, close = _workload_tasks(
                name=name,
                kind=str(w["kind"]),
                peer=str(w["peer"]),
                claims=[dict(c) for c in (w.get("claims") or [])],
                horizon_s=float(w["horizon_s"]),
                reason=str(w.get("reason") or ""),
                precludes=w.get("precludes"),
                postures=w.get("postures"),
                owner=w.get("owner"),
                pool=w.get("pool"),
                poll_s=poll_s,
                suffix=f"_{name}",
            )
            if prev_close is not None:
                prev_close >> declare
            prev_close = close
    return dag
