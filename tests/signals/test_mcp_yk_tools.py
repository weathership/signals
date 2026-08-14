"""MCP tool dispatch unit tests (no live engine)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from signals.mcp.yk import TOOLS, call_tool, handle_message


def test_tools_list_covers_promote_and_ops():
    names = {t["name"] for t in TOOLS}
    assert "yk_health" in names
    assert "yk_promote" in names
    assert "yk_write_scratch" in names
    assert "yk_diff" in names


def test_call_tool_health():
    stub = MagicMock()
    check = MagicMock()
    check.succeeded = True
    check.name = "Scheduling errors"
    check.diagnosis = ""
    check.description = "ok"
    stub.Health.return_value = MagicMock(healthy=True, checks=[check])
    with patch("signals.mcp.yk._stub", return_value=stub):
        r = call_tool("yk_health", {})
    assert not r["isError"]
    assert "healthy" in r["content"][0]["text"]


def test_call_tool_promote_dry_run():
    stub = MagicMock()
    stub.PromoteScratch.return_value = MagicMock(
        ok=True,
        applied=False,
        archive_id="",
        message="dry_run: validation ok",
    )
    with patch("signals.mcp.yk._stub", return_value=stub):
        r = call_tool("yk_promote", {"dry_run": True})
    assert not r["isError"]
    assert "dry_run" in r["content"][0]["text"]
    req = stub.PromoteScratch.call_args[0][0]
    assert req.dry_run is True


def test_handle_initialize_and_tools_list(capsys):
    handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2
    assert "signals-yk" in out[0]
    assert "yk_promote" in out[1]
