#!/usr/bin/env python3
"""Probe zndx.engine.v1.Engine/Status using *generated* signals-protocol stubs.

The proto is the specification (OIP-aligned). This client is code-generated from
``components/signals-protocol/proto`` — not a parallel informal probe.

Server reflection is a separate *install* requirement so external tools can use
bare ``grpcurl host:port Service/Method`` without local descriptor flags.
This script implements the protocol properly via codegen.

Usage:
  uv run python scripts/zndx_engine_status.py 127.0.0.1:50551
  uv run python scripts/zndx_engine_status.py --json 127.0.0.1:50551
  uv run python scripts/zndx_engine_status.py --query remotes 127.0.0.1:50551
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


_QUERY_KINDS = {
    "remotes": "SERVER_QUERY_KIND_REMOTES",
    "schedules": "SERVER_QUERY_KIND_SCHEDULES",
    "peers": "SERVER_QUERY_KIND_PEERS",
    "surfaces": "SERVER_QUERY_KIND_SURFACES",
    "queues": "SERVER_QUERY_KIND_QUEUES",
}


def _stub(target: str):
    import grpc
    from zndx.engine.v1 import engine_pb2_grpc

    channel = grpc.insecure_channel(target)
    return engine_pb2_grpc.EngineStub(channel)


def _status(target: str, timeout: float):
    from zndx.engine.v1 import engine_pb2

    return _stub(target).Status(engine_pb2.StatusRequest(), timeout=timeout)


def _server_query(target: str, kind_name: str, timeout: float):
    from zndx.engine.v1 import engine_pb2

    kind = getattr(engine_pb2, _QUERY_KINDS[kind_name])
    return _stub(target).ServerQuery(
        engine_pb2.ServerQueryRequest(kind=kind, origin_project="signals"),
        timeout=timeout,
    )


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
    surfaces = []
    for s in getattr(resp, "surfaces", []) or []:
        surfaces.append({"kind": s.kind, "url": s.url, "healthy": s.healthy})
    return {
        "project": resp.project,
        "endpoints": eps,
        "total_gpus": resp.total_gpus,
        "surfaces": surfaces,
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
    ap.add_argument(
        "--query",
        choices=sorted(_QUERY_KINDS),
        help="Engine/ServerQuery kind instead of Status",
    )
    args = ap.parse_args()

    if args.query:
        try:
            q = _server_query(args.target, args.query, args.timeout)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: ServerQuery failed: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    {
                        "project": q.project,
                        "head": q.head,
                        "remotes": [{"name": r.name, "url": r.url} for r in q.remotes],
                        "peers": [
                            {"project": p.project, "target": p.target} for p in q.peers
                        ],
                        "surfaces": [
                            {"kind": s.kind, "url": s.url, "healthy": s.healthy}
                            for s in q.surfaces
                        ],
                    },
                    indent=2,
                )
            )
        else:
            print(f"project={q.project} head={q.head or '—'} remotes={len(q.remotes)}")
            for r in q.remotes:
                print(f"  remote {r.name} {r.url}")
            for s in q.surfaces:
                print(f"  surface {s.kind} {s.url}")
            for p in q.peers:
                print(f"  peer {p.project} {p.target}")
        return 0

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
        print(
            f"project={data['project']} endpoints={len(data['endpoints'])} "
            f"total_gpus={data['total_gpus']} surfaces={len(data.get('surfaces') or [])}"
        )
        for s in data.get("surfaces") or []:
            print(f"  surface {s.get('kind') or '?'} {s.get('url') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
