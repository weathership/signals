"""Resolve project → lattice host:port from peer-contract.json."""

from __future__ import annotations

import json
import os
from pathlib import Path


def contract_path() -> Path:
    env = os.environ.get("SIGNALS_PEER_CONTRACT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    return here.parents[3] / "config" / "platform" / "peer-contract.json"


def lattice_target(project: str, path: Path | None = None) -> str:
    """Return host:port for the project's Engine (lab insecure)."""
    host = os.environ.get("SIGNALS_ENGINE_YIELD_HOST", "127.0.0.1")
    override = os.environ.get("SIGNALS_C2_YIELD_TARGET")
    if override and (not project or project == "signals"):
        return override
    doc = json.loads((path or contract_path()).read_text(encoding="utf-8"))
    want = (project or "signals").strip().lower()
    for peer in doc.get("peers") or []:
        if str(peer.get("id", "")).lower() == want:
            port = int(peer.get("grpc_port") or 0)
            if port:
                return f"{host}:{port}"
    lattice = doc.get("engine_grpc_lattice") or {}
    port = lattice.get(want) or lattice.get("signals") or 50551
    return f"{host}:{int(port)}"
