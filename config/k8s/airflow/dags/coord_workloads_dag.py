"""coord_workloads — the federation's workload catalogue as Airflow DAGs.

Dynamic DAG generation from the ``zndx_workloads`` Variable, which the Signals
engine writes when a peer engine SUBMITS its workload catalogue
(``zndx.scheduler.v1.Scheduler/SyncWorkloads``). Nobody edits the Variable by
hand; nobody outside Signals talks to Airflow.

For every registry entry with a ``dag_id`` (``source != engine``) this module
builds ONE workload DAG with ``coord_signals.make_workload_dag``:

  declare → hold → close      (the run IS a Coordination Activity)

  * ``cron`` entries are time-scheduled (project-local ``timezone``, UTC default);
  * ``after`` entries are **Asset-scheduled** on the named workloads' ended
    Assets (``zndx.coord.<kind>.ended``) — "when one workload completes, the
    next runs and asserts its queue configuration", in Airflow's own terms;
  * ``enabled = false`` entries are born PAUSED: catalogued and visible, never
    scheduled until the owner enables them (the procession is visible before it
    is live).

The workload's ``claims`` are its YuniKorn queue configuration: the run's
``declare`` hands them to Signals, which asserts them into the arbiter for the
run's duration and retires them when the run closes.

Airflow dynamic-DAG hygiene: cheap at parse time (one Variable read, no other
network), deterministic dag_ids, ``globals()[dag_id] = dag``. An absent Variable
is an empty catalogue, logged once — not an error and not a stand-in.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import pendulum

# The metadata-DB accessor: the dag-processor (this deployment's LocalExecutor
# pods) reads it at parse time. `airflow.sdk.Variable` only resolves inside a
# task/parse supervisor context (verified 2026-09-07: VARIABLE_NOT_FOUND from a
# plain process while the Variable existed).
from airflow.models import Variable

from coord_signals import ended_asset_for, make_workload_dag

log = logging.getLogger("coord_workloads")

REGISTRY_KEY = "zndx_workloads"
SOURCE_ENGINE = "engine"
# Migration day: no back-interval run is created for a freshly materialised cron DAG.
CATALOGUE_START = datetime(2026, 9, 7, tzinfo=timezone.utc)


def _load_registry() -> dict[str, Any]:
    raw = Variable.get(REGISTRY_KEY, default_var=None, deserialize_json=True)
    if raw is None:
        log.info("coord_workloads: Variable %s absent — empty catalogue", REGISTRY_KEY)
        return {"workloads": []}
    if isinstance(raw, str):  # a serializer that hands the string back
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError(f"coord_workloads: Variable {REGISTRY_KEY} is not a JSON object")
    return raw


def _schedule_for(entry: dict[str, Any]) -> Any:
    cron = (entry.get("cron") or "").strip()
    after_kinds = [k for k in (entry.get("after_kinds") or []) if k]
    if cron:
        return cron
    if after_kinds:
        return [ended_asset_for(k) for k in after_kinds]
    return None  # manual / engine-triggered only


def _start_date(entry: dict[str, Any]) -> datetime:
    tz = (entry.get("timezone") or "").strip()
    if not tz:
        return CATALOGUE_START
    return pendulum.datetime(2026, 9, 7, tz=tz)


def build(registry: dict[str, Any]) -> dict[str, Any]:
    dags: dict[str, Any] = {}
    for entry in registry.get("workloads") or []:
        if not isinstance(entry, dict):
            continue
        dag_id = (entry.get("dag_id") or "").strip()
        if not dag_id or (entry.get("source") or "") == SOURCE_ENGINE:
            continue  # declared by its engine at session start; catalogued for visibility only
        if dag_id in dags:
            raise ValueError(f"coord_workloads: duplicate dag_id {dag_id!r} in the registry")
        peer = str(entry.get("peer") or "")
        kind = str(entry.get("kind") or "")
        enabled = bool(entry.get("enabled", True))
        dags[dag_id] = make_workload_dag(
            dag_id,
            kind=kind,
            peer=peer,
            claims=[dict(c) for c in (entry.get("claims") or [])],
            horizon_s=float(entry.get("horizon_s") or 3600),
            schedule=_schedule_for(entry),
            reason=str(entry.get("description") or f"{peer} {kind} (catalogued workload)"),
            precludes=list(entry.get("precludes") or []) or None,
            postures=dict(entry.get("postures") or {}) or None,
            tags=[peer, kind, "workload", "catalogue", str(entry.get("runner") or "")],
            description=str(entry.get("description") or f"{peer}: {kind} — catalogued workload as a Coordination Activity"),
            start_date=_start_date(entry),
            catchup=False,
            paused=not enabled,
        )
    return dags


_REGISTRY = _load_registry()
for _dag_id, _dag in build(_REGISTRY).items():
    globals()[_dag_id] = _dag
log.info(
    "coord_workloads: registry v%s → %d DAG(s)",
    _REGISTRY.get("version", "?"),
    sum(1 for e in (_REGISTRY.get("workloads") or []) if e.get("dag_id") and e.get("source") != SOURCE_ENGINE),
)
