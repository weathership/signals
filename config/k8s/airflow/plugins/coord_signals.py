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
from airflow.sdk import Asset
from airflow.sdk.bases.sensor import BaseSensorOperator, PokeReturnValue
from airflow.triggers.base import BaseTrigger, TriggerEvent

import coord_lease

log = logging.getLogger("coord_signals")

GURU_BADEVENT = "#CO.00000008.BADEVENT"

ACTIVITY_STARTED = Asset("zndx.coord.activity")
ACTIVITY_ENDED = Asset("zndx.coord.activity.ended")

DEFAULT_POLL_S = 5.0
DEFAULT_HOLD_TIMEOUT = timedelta(hours=24)  # outer net only; the lease decides


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
