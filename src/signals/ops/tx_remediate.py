"""Surface a non-v7 tx_id to the source engine via Engine/Remediate."""

from __future__ import annotations

from typing import Any

from signals.uuidv7 import NonUuid7TxId

DEFAULT_CAPABILITY = "reauthor"


def remediation_request(err: NonUuid7TxId, *, capability: str = DEFAULT_CAPABILITY) -> dict[str, Any]:
    """Dict shaped like zndx.engine.v1.RemediationRequest (no generated import required)."""
    sig = err.boundary_signal()
    return {
        "capability": capability,
        "signal": {
            "kind": sig["kind"],
            "kind_number": sig["kind_number"],
            "subject": sig["subject"],
            "offending": sig["offending"],
            "reason": sig["reason"],
            "authority": sig["authority"],
        },
        "context": {
            "rules": [
                "tx_id MUST be RFC 9562 UUID version 7",
                "Implementations SHOULD utilize v7 over v1 and v6",
                "Remint and resubmit; warehouse will not store the rejected id",
            ],
            "justification": [f"source={err.source}"] if err.source else [],
        },
    }


def to_proto(err: NonUuid7TxId, *, capability: str = DEFAULT_CAPABILITY):
    """Build a generated RemediationRequest for a live Engine/Remediate call."""
    from signals.engine.generated.zndx.engine.v1 import engine_pb2

    req = remediation_request(err, capability=capability)
    sig = req["signal"]
    return engine_pb2.RemediationRequest(
        capability=req["capability"],
        signal=engine_pb2.BoundarySignal(
            kind=engine_pb2.TX_ID_NOT_UUIDV7,
            subject=sig["subject"],
            offending=sig["offending"],
            reason=sig["reason"],
            authority=sig["authority"],
        ),
        context=engine_pb2.SignalContext(
            justification=list(req["context"]["justification"]),
            rules=list(req["context"]["rules"]),
        ),
    )


def surface(err: NonUuid7TxId, target: str, *, timeout: float = 10.0) -> Any:
    """Call Engine/Remediate on *target* (`host:port`). Caller still owns disposition."""
    import grpc

    from signals.engine.generated.zndx.engine.v1 import engine_pb2_grpc

    req = to_proto(err)
    channel = grpc.insecure_channel(target)
    try:
        stub = engine_pb2_grpc.EngineStub(channel)
        return stub.Remediate(req, timeout=timeout)
    finally:
        channel.close()
