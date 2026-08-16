"""Engine/Yield ends an attached lab proof process."""

from __future__ import annotations

from unittest.mock import MagicMock

from signals.engine.generated.zndx.engine.v1 import engine_pb2
from signals.engine.servicers.engine_status import SignalsEngineServicer
from signals.engine.workloads import WorkloadTable, _pid_alive


def test_yield_unknown_id_idempotent():
    svc = SignalsEngineServicer("signals", yk=MagicMock(), workloads=WorkloadTable())
    r = svc.Yield(engine_pb2.YieldRequest(workload_id="missing"), context=None)
    assert r.ok
    assert not r.process_ended
    assert "no local process" in r.message


def test_yield_ends_attached_pid():
    table = WorkloadTable()
    row = table.attach("proof-1")
    assert _pid_alive(row.pid)
    svc = SignalsEngineServicer("signals", yk=MagicMock(), workloads=table)
    r = svc.Yield(
        engine_pb2.YieldRequest(
            workload_id="proof-1",
            reason=engine_pb2.YIELD_REASON_PREEMPTED,
        ),
        context=None,
    )
    assert r.ok
    assert r.process_ended
    assert not _pid_alive(row.pid)
    # second yield is idle
    r2 = svc.Yield(engine_pb2.YieldRequest(workload_id="proof-1"), context=None)
    assert r2.ok
    assert not r2.process_ended
