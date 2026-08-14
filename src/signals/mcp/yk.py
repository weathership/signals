"""signals-yk MCP server — API-symmetric thin client over zndx.scheduler.v1.

Speaks a minimal MCP stdio JSON-RPC surface (initialize / tools/list / tools/call)
without depending on the full ``mcp`` Python package (avoids fragile transitive
deps in lab shells). Product path is engine gRPC only.

Run::

    export SIGNALS_ENGINE_TARGET=127.0.0.1:50551
    uv run python -m signals.mcp.yk
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import grpc

_ROOT = Path(__file__).resolve().parents[1] / "engine" / "generated"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from zndx.scheduler.v1 import scheduler_pb2, scheduler_pb2_grpc  # noqa: E402

SERVER_NAME = "signals-yk"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


def _stub() -> scheduler_pb2_grpc.SchedulerStub:
    target = os.environ.get("SIGNALS_ENGINE_TARGET", "127.0.0.1:50551")
    return scheduler_pb2_grpc.SchedulerStub(grpc.insecure_channel(target))


def _text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": content}]


def _tool_err(msg: str) -> dict[str, Any]:
    return {"content": _text(msg), "isError": True}


def _tool_ok(msg: str) -> dict[str, Any]:
    return {"content": _text(msg), "isError": False}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "yk_health",
        "description": "Scheduler health via Signals engine (zndx.scheduler.v1.Health).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "yk_partitions",
        "description": "List scheduler partitions via engine.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "yk_queues",
        "description": "Print queue tree for a partition.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string", "default": "default"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "yk_config",
        "description": "Get declared queues.yaml from live YK via engine.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "yk_validate",
        "description": "Validate a queues.yaml body via engine ValidateConfig.",
        "inputSchema": {
            "type": "object",
            "properties": {"yaml": {"type": "string"}},
            "required": ["yaml"],
            "additionalProperties": False,
        },
    },
    {
        "name": "yk_sync",
        "description": "Sync current projection from live YK.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string", "default": "default"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "yk_write_scratch",
        "description": "Write scratch queues.yaml (pending promote).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "yaml": {"type": "string"},
                "rebuild_notes": {"type": "boolean", "default": True},
            },
            "required": ["yaml"],
            "additionalProperties": False,
        },
    },
    {
        "name": "yk_diff",
        "description": "Diff scratch vs current (optionally vs live).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_live": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "yk_promote",
        "description": (
            "Promote scratch → validate + ConfigMap apply + archive + current. "
            "Use dry_run=true for validation + kubectl dry-run only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False},
                "archive_stamp": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "yk_archives",
        "description": "List projection archives.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "yk_restore",
        "description": "Restore an archive into scratch.",
        "inputSchema": {
            "type": "object",
            "properties": {"archive_id": {"type": "string"}},
            "required": ["archive_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "yk_index",
        "description": "List projection notes for lineup navigation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "enum": ["current", "scratch", "archive"],
                    "default": "current",
                },
                "archive_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
]


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}
    try:
        stub = _stub()
        if name == "yk_health":
            r = stub.Health(scheduler_pb2.HealthRequest(), timeout=15)
            lines = ["healthy" if r.healthy else "unhealthy"]
            for c in r.checks:
                mark = "ok" if c.succeeded else "FAIL"
                lines.append(f"  {mark} {c.name}: {c.diagnosis or c.description}")
            return _tool_ok("\n".join(lines))

        if name == "yk_partitions":
            r = stub.ListPartitions(scheduler_pb2.ListPartitionsRequest(), timeout=15)
            lines = [f"{p.name}\t{p.state}\tnodes={p.total_nodes}" for p in r.partitions]
            return _tool_ok("\n".join(lines) or "(none)")

        if name == "yk_queues":
            part = str(args.get("partition") or "default")
            r = stub.GetQueueTree(
                scheduler_pb2.GetQueueTreeRequest(partition=part), timeout=15
            )
            lines: list[str] = []

            def walk(n, indent=0):
                pad = "  " * indent
                leaf = "leaf" if n.is_leaf else "parent"
                mem = n.allocated.quantities.get("memory", 0)
                lines.append(
                    f"{pad}{n.name}  {n.status}  {leaf}  "
                    f"alloc_mem={mem}  running={n.running_apps}"
                )
                for c in n.children:
                    walk(c, indent + 1)

            walk(r.root)
            return _tool_ok("\n".join(lines))

        if name == "yk_config":
            r = stub.GetDeclaredConfig(
                scheduler_pb2.GetDeclaredConfigRequest(), timeout=15
            )
            return _tool_ok((r.document.body if r.document else "") or "")

        if name == "yk_validate":
            yaml_body = str(args.get("yaml") or "")
            r = stub.ValidateConfig(
                scheduler_pb2.ValidateConfigRequest(
                    document=scheduler_pb2.PolicyDocument(
                        media_type="text/yaml", body=yaml_body
                    )
                ),
                timeout=30,
            )
            msg = f"{'ok' if r.ok else 'FAIL'} {r.message}"
            if r.errors:
                msg += "\n" + "\n".join(f"  {e}" for e in r.errors)
            return _tool_ok(msg) if r.ok else _tool_err(msg)

        if name == "yk_sync":
            part = str(args.get("partition") or "default")
            r = stub.SyncProjection(
                scheduler_pb2.SyncProjectionRequest(partition=part), timeout=60
            )
            return _tool_ok(f"notes_written={r.notes_written} config={r.config_path}")

        if name == "yk_write_scratch":
            yaml_body = str(args.get("yaml") or "")
            rebuild = bool(args.get("rebuild_notes", True))
            r = stub.WriteScratchConfig(
                scheduler_pb2.WriteScratchConfigRequest(
                    document=scheduler_pb2.PolicyDocument(
                        media_type="text/yaml", body=yaml_body
                    ),
                    rebuild_notes=rebuild,
                ),
                timeout=30,
            )
            return _tool_ok(r.message) if r.ok else _tool_err(r.message)

        if name == "yk_diff":
            r = stub.DiffConfig(
                scheduler_pb2.DiffConfigRequest(
                    include_live=bool(args.get("include_live", False))
                ),
                timeout=30,
            )
            parts = [r.unified_diff or "(no scratch vs current diff)"]
            if args.get("include_live"):
                parts.append("--- live vs current ---")
                parts.append(r.live_diff or "(no live vs current diff)")
            return _tool_ok("\n".join(parts))

        if name == "yk_promote":
            r = stub.PromoteScratch(
                scheduler_pb2.PromoteScratchRequest(
                    dry_run=bool(args.get("dry_run", False)),
                    archive_stamp=str(args.get("archive_stamp") or ""),
                ),
                timeout=120,
            )
            msg = (
                f"{'ok' if r.ok else 'FAIL'} applied={r.applied} "
                f"archive={r.archive_id or '—'} {r.message}"
            )
            return _tool_ok(msg) if r.ok else _tool_err(msg)

        if name == "yk_archives":
            r = stub.ListArchives(scheduler_pb2.ListArchivesRequest(), timeout=15)
            if not r.archives:
                return _tool_ok("(no archives)")
            lines = [f"{a.id}\t{a.created_at}\t{a.note}".rstrip() for a in r.archives]
            return _tool_ok("\n".join(lines))

        if name == "yk_restore":
            aid = str(args.get("archive_id") or "")
            r = stub.RestoreArchiveToScratch(
                scheduler_pb2.RestoreArchiveToScratchRequest(archive_id=aid),
                timeout=30,
            )
            return _tool_ok(r.message) if r.ok else _tool_err(r.message)

        if name == "yk_index":
            root_name = str(args.get("root") or "current")
            root = {
                "current": scheduler_pb2.CURRENT,
                "scratch": scheduler_pb2.SCRATCH,
                "archive": scheduler_pb2.ARCHIVE,
            }.get(root_name, scheduler_pb2.CURRENT)
            r = stub.GetProjectionIndex(
                scheduler_pb2.GetProjectionIndexRequest(
                    root=root, archive_id=str(args.get("archive_id") or "")
                ),
                timeout=15,
            )
            lines = [f"total={r.total}"]
            for n in r.notes:
                lines.append(f"  {n.id}  [{n.kind}]  {n.title}")
            return _tool_ok("\n".join(lines))

        return _tool_err(f"unknown tool: {name}")
    except grpc.RpcError as e:
        return _tool_err(f"gRPC {e.code()}: {e.details()}")
    except Exception as e:  # noqa: BLE001
        return _tool_err(str(e))


def _respond(msg_id: Any, result: Any) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n"
    )
    sys.stdout.flush()


def _respond_error(msg_id: Any, code: int, message: str) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": code, "message": message},
            }
        )
        + "\n"
    )
    sys.stdout.flush()


def handle_message(msg: dict[str, Any]) -> None:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    # notifications (no id)
    if msg_id is None:
        return

    if method == "initialize":
        _respond(
            msg_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
        return

    if method == "ping":
        _respond(msg_id, {})
        return

    if method == "tools/list":
        _respond(msg_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        name = params.get("name") or ""
        arguments = params.get("arguments") or {}
        result = call_tool(name, arguments)
        _respond(msg_id, result)
        return

    if method == "resources/list":
        _respond(msg_id, {"resources": []})
        return

    if method == "prompts/list":
        _respond(msg_id, {"prompts": []})
        return

    _respond_error(msg_id, -32601, f"Method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        handle_message(msg)


if __name__ == "__main__":
    main()
