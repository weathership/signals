"""gRPC client: C2 → zndx.engine.v1.Engine/Yield."""

from __future__ import annotations

import logging

log = logging.getLogger("signals.c2.yield")


def yield_workload(
    target: str,
    *,
    workload_id: str,
    reason: str = "PREEMPTED",
    sentinel_id: str = "",
    detail: str = "",
    timeout_s: float = 10.0,
) -> dict:
    import grpc

    try:
        from signals.engine.generated.zndx.engine.v1 import (
            engine_pb2,
            engine_pb2_grpc,
        )
    except ImportError:  # scripts/generated on PYTHONPATH
        from zndx.engine.v1 import engine_pb2, engine_pb2_grpc

    reason_map = {
        "UNSPECIFIED": engine_pb2.YIELD_REASON_UNSPECIFIED,
        "PREEMPTED": engine_pb2.YIELD_REASON_PREEMPTED,
        "COMPLETED": engine_pb2.YIELD_REASON_COMPLETED,
        "ORPHAN": engine_pb2.YIELD_REASON_ORPHAN,
        "UNIT_STOP": engine_pb2.YIELD_REASON_UNIT_STOP,
    }
    enum = reason_map.get(reason.upper(), engine_pb2.YIELD_REASON_PREEMPTED)
    channel = grpc.insecure_channel(target)
    stub = engine_pb2_grpc.EngineStub(channel)
    resp = stub.Yield(
        engine_pb2.YieldRequest(
            workload_id=workload_id,
            reason=enum,
            sentinel_id=sentinel_id,
            detail=detail,
        ),
        timeout=timeout_s,
    )
    return {
        "ok": bool(resp.ok),
        "process_ended": bool(resp.process_ended),
        "restore_started": bool(resp.restore_started),
        "message": resp.message,
        "target": target,
    }
