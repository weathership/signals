"""signals-yk / signals-sched — thin CLI over zndx.scheduler.v1 (engine gRPC)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import grpc

# Ensure generated stubs importable
_ROOT = Path(__file__).resolve().parents[1] / "engine" / "generated"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from zndx.scheduler.v1 import scheduler_pb2, scheduler_pb2_grpc  # noqa: E402


def _channel() -> grpc.Channel:
    target = os.environ.get("SIGNALS_ENGINE_TARGET", "127.0.0.1:50551")
    return grpc.insecure_channel(target)


def _stub() -> scheduler_pb2_grpc.SchedulerStub:
    return scheduler_pb2_grpc.SchedulerStub(_channel())


def cmd_partitions(_: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.ListPartitions(scheduler_pb2.ListPartitionsRequest(), timeout=15)
    for p in r.partitions:
        print(f"{p.name}  {p.state}  nodes={p.total_nodes}")
    return 0


def cmd_queues(ns: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.GetQueueTree(
        scheduler_pb2.GetQueueTreeRequest(partition=ns.partition or "default"),
        timeout=15,
    )

    def walk(n, indent=0):
        pad = "  " * indent
        leaf = "leaf" if n.is_leaf else "parent"
        mem = n.allocated.quantities.get("memory", 0)
        print(
            f"{pad}{n.name}  {n.status}  {leaf}  "
            f"alloc_mem={mem}  running={n.running_apps}"
        )
        for c in n.children:
            walk(c, indent + 1)

    walk(r.root)
    return 0


def cmd_config(_: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.GetDeclaredConfig(scheduler_pb2.GetDeclaredConfigRequest(), timeout=15)
    body = r.document.body if r.document else ""
    sys.stdout.write(body)
    if body and not body.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def cmd_validate(ns: argparse.Namespace) -> int:
    path = Path(ns.file)
    yaml_body = path.read_text(encoding="utf-8")
    stub = _stub()
    r = stub.ValidateConfig(
        scheduler_pb2.ValidateConfigRequest(
            document=scheduler_pb2.PolicyDocument(
                media_type="text/yaml", body=yaml_body
            )
        ),
        timeout=30,
    )
    print("ok" if r.ok else "FAIL", r.message)
    for e in r.errors:
        print(" ", e)
    return 0 if r.ok else 1


def cmd_sync(ns: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.SyncProjection(
        scheduler_pb2.SyncProjectionRequest(partition=ns.partition or "default"),
        timeout=60,
    )
    print(f"notes_written={r.notes_written} config={r.config_path}")
    return 0


def cmd_health(_: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.Health(scheduler_pb2.HealthRequest(), timeout=15)
    print(
        ("healthy" if r.healthy else "unhealthy")
        + (f" backend={r.backend}" if r.backend else "")
    )
    for c in r.checks:
        mark = "✓" if c.succeeded else "✗"
        print(f"  {mark} {c.name}: {c.diagnosis or c.description}")
    return 0 if r.healthy else 1


def cmd_write_scratch(ns: argparse.Namespace) -> int:
    if ns.file == "-":
        yaml_body = sys.stdin.read()
    else:
        yaml_body = Path(ns.file).read_text(encoding="utf-8")
    stub = _stub()
    r = stub.WriteScratchConfig(
        scheduler_pb2.WriteScratchConfigRequest(
            document=scheduler_pb2.PolicyDocument(
                media_type="text/yaml", body=yaml_body
            ),
            rebuild_notes=not ns.no_notes,
        ),
        timeout=30,
    )
    print("ok" if r.ok else "FAIL", r.message)
    return 0 if r.ok else 1


def cmd_diff(ns: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.DiffConfig(
        scheduler_pb2.DiffConfigRequest(include_live=ns.live),
        timeout=30,
    )
    if r.unified_diff:
        sys.stdout.write(r.unified_diff)
        if not r.unified_diff.endswith("\n"):
            sys.stdout.write("\n")
    else:
        print("(no scratch vs current diff)")
    if ns.live:
        print("--- live vs current ---")
        if r.live_diff:
            sys.stdout.write(r.live_diff)
            if not r.live_diff.endswith("\n"):
                sys.stdout.write("\n")
        else:
            print("(no live vs current diff)")
    return 0


def cmd_promote(ns: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.PromoteScratch(
        scheduler_pb2.PromoteScratchRequest(
            dry_run=ns.dry_run,
            archive_stamp=ns.stamp or "",
        ),
        timeout=120,
    )
    print(
        f"{'ok' if r.ok else 'FAIL'} applied={r.applied} archive={r.archive_id or '—'} "
        f"{r.message}"
    )
    if r.validation.message:
        print(f"  validation: {'ok' if r.validation.ok else 'FAIL'} {r.validation.message}")
    return 0 if r.ok else 1


def cmd_archives(_: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.ListArchives(scheduler_pb2.ListArchivesRequest(), timeout=15)
    if not r.archives:
        print("(no archives)")
        return 0
    for a in r.archives:
        print(f"{a.id}  {a.created_at}  {a.note}".rstrip())
    return 0


def cmd_restore(ns: argparse.Namespace) -> int:
    stub = _stub()
    r = stub.RestoreArchiveToScratch(
        scheduler_pb2.RestoreArchiveToScratchRequest(archive_id=ns.archive_id),
        timeout=30,
    )
    print("ok" if r.ok else "FAIL", r.message)
    return 0 if r.ok else 1


def cmd_index(ns: argparse.Namespace) -> int:
    stub = _stub()
    root = {
        "current": scheduler_pb2.CURRENT,
        "scratch": scheduler_pb2.SCRATCH,
        "archive": scheduler_pb2.ARCHIVE,
    }.get(ns.root or "current", scheduler_pb2.CURRENT)
    r = stub.GetProjectionIndex(
        scheduler_pb2.GetProjectionIndexRequest(
            root=root, archive_id=ns.archive_id or ""
        ),
        timeout=15,
    )
    print(f"total={r.total}")
    for n in r.notes:
        print(f"  {n.id}  [{n.kind}]  {n.title}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="signals-yk",
        description="Thin CLI for zndx.scheduler.v1 via Signals engine gRPC "
        "(SIGNALS_ENGINE_TARGET, default 127.0.0.1:50551). Lab backend: YuniKorn.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("partitions", help="List partitions").set_defaults(func=cmd_partitions)

    q = sub.add_parser("queues", help="Print queue tree")
    q.add_argument("--partition", default="default")
    q.set_defaults(func=cmd_queues)

    sub.add_parser("config", help="Print declared queues.yaml").set_defaults(func=cmd_config)

    v = sub.add_parser("validate", help="Validate a queues.yaml file")
    v.add_argument("file")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("sync", help="Sync current projection from live YK")
    s.add_argument("--partition", default="default")
    s.set_defaults(func=cmd_sync)

    sub.add_parser("health", help="YK healthcheck via engine").set_defaults(func=cmd_health)

    ws = sub.add_parser("write-scratch", help="Write scratch queues.yaml from file or stdin")
    ws.add_argument("file", help="path or - for stdin")
    ws.add_argument(
        "--no-notes",
        action="store_true",
        help="skip rebuilding scratch queue notes from YAML",
    )
    ws.set_defaults(func=cmd_write_scratch)

    d = sub.add_parser("diff", help="Diff scratch vs current (optional vs live)")
    d.add_argument(
        "--live",
        action="store_true",
        help="also diff live GetDeclaredConfig vs current",
    )
    d.set_defaults(func=cmd_diff)

    pr = sub.add_parser(
        "promote",
        help="Validate + apply scratch → cluster ConfigMap + current projection",
    )
    pr.add_argument(
        "--dry-run",
        action="store_true",
        help="validate + kubectl dry-run only; do not write projection",
    )
    pr.add_argument("--stamp", default="", help="archive stamp (default: auto UTC)")
    pr.set_defaults(func=cmd_promote)

    sub.add_parser("archives", help="List projection archives").set_defaults(
        func=cmd_archives
    )

    rs = sub.add_parser("restore", help="Restore an archive into scratch")
    rs.add_argument("archive_id")
    rs.set_defaults(func=cmd_restore)

    idx = sub.add_parser("index", help="List projection notes (lineup index)")
    idx.add_argument(
        "--root",
        choices=("current", "scratch", "archive"),
        default="current",
    )
    idx.add_argument("--archive-id", default="")
    idx.set_defaults(func=cmd_index)

    ns = p.parse_args(argv)
    try:
        return int(ns.func(ns))
    except grpc.RpcError as e:
        print(f"gRPC error: {e.code()} {e.details()}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
