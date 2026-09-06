"""Coordination Activity DAGs — inter-project intent with a lifetime, OBSERVED.

One run = one Activity. The Signals engine is the only party that triggers
these runs (``zndx.scheduler.v1.Scheduler`` Declare; peer engines never call
Airflow) and the only party the run observes: the ``hold`` task is a
deferrable ``SignalsActivitySensor`` whose trigger polls the activity's LEASE
on the Signals engine (heartbeat, horizon, TTL, released flag). Renew is a
heartbeat on that lease; Release flips it; the run completes when the sensor
sees either — nobody patches a run's state.

  running                       → intent in force
  success, lease released       → RELEASED (owner released before the horizon)
  success, lease not released   → EXPIRED (heartbeats stopped or horizon passed)
  failed                        → FAILED (intent NOT in force)

Two DAGs from one factory (plugins/coord_signals.py):
  coord_interactive_session — kind interactive_session; the hold task occupies
                              Airflow pool ``agent_rtc`` (1 slot, deferred
                              included): the agent-rtc leaf's claim in Airflow's
                              own vocabulary.
  coord_activity            — every other kind (curation_window, restart_window,
                              maintenance_pause, …).

Tasks: ``declare`` (emits Asset ``zndx.coord.activity``) → ``hold`` → ``close``
(emits Asset ``zndx.coord.activity.ended``) so other DAGs can schedule on an
activity's start or end.

Spec: signals-protocol specification/protocol/coordination_activities.md
"""

from __future__ import annotations

from coord_signals import make_coord_dag

coord_interactive_session = make_coord_dag(
    "coord_interactive_session",
    description="Coordination Activity: an agent-rtc interactive session (Signals-observed; pool agent_rtc)",
    pool="agent_rtc",
)

coord_activity = make_coord_dag(
    "coord_activity",
    description="Coordination Activity: inter-project intent with a lifetime (Signals-observed)",
)
