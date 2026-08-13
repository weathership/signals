#!/usr/bin/env python3
"""Probe zndx.engine.v1.Engine/Status using *generated* signals-protocol stubs.

The proto is the specification (OIP-aligned). This client is code-generated from
``components/signals-protocol/proto`` — not a parallel informal probe.

Server reflection is a separate *install* requirement so external tools can use
bare ``grpcurl host:port Service/Method`` without local descriptor flags.
This script implements the protocol properly via codegen.

Usage:
  uv run python scripts/zndx_engine_status.py 127.0.0.1:50051
  uv run python scripts/zndx_engine_status.py --json 127.0.0.1:50051
  uv run python scripts/zndx_engine_status.py --expect-project gaius 127.0.0.1:50051

Exit 0 on successful Status RPC; 1 on failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts" / "generated"
if str(GEN) not in sys.path:
    sys.path.insert(0, str(GEN))


def _status(target: str, timeout: float):
    import grpc
    from zndx.engine.v1 import engine_pb2, engine_pb2_grpc

    channel = grpc.insecure_channel(target)
    stub = engine_pb2_grpc.EngineStub(channel)
    return stub.Status(engine_pb2.StatusRequest(), timeout=timeout)


def _to_dict(resp) -> dict:
    eps = []
    for e in resp.endpoints:
        eps.append(
            {
                "capability": e.capability,
                "model": e.model,
                "healthy": e.healthy,
                "gpu_ids": list(e.gpu_ids),
                "detail": e.detail,
            }
        )
    return {
        "project": resp.project,
        "endpoints": eps,
        "total_gpus": resp.total_gpus,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="host:port of lattice Engine")
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--json", action="store_true", help="print full Status as JSON")
    ap.add_argument("--expect-project", default="", help="require Status.project match")
    ap.add_argument(
        "--expect-capability",
        default="",
        help="soft: require substring match in endpoints/capabilities",
    )
    args = ap.parse_args()

    try:
        resp = _status(args.target, args.timeout)
    except Exception as e:  # noqa: BLE001 — surface for lattice-ci
        print(f"ERROR: Status RPC failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    data = _to_dict(resp)
    if args.expect_project and data["project"] != args.expect_project:
        print(
            f"ERROR: project={data['project']!r} expected {args.expect_project!r}",
            file=sys.stderr,
        )
        return 1
    if args.expect_capability:
        caps = " ".join(
            f"{e.get('capability','')} {e.get('model','')} {e.get('detail','')}"
            for e in data["endpoints"]
        )
        if args.expect_capability.lower() not in (data["project"] + " " + caps).lower():
            print(
                f"ERROR: capability {args.expect_capability!r} not found in Status",
                file=sys.stderr,
            )
            return 1

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"project={data['project']} endpoints={len(data['endpoints'])} total_gpus={data['total_gpus']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
