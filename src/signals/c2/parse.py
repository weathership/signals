"""Extract workload_id / phase / project from a C2 heartbeat or last-gasp."""

from __future__ import annotations

from typing import Any


def _walk_str(obj: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(obj, dict):
        return ""
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def parse_heartbeat(body: dict[str, Any]) -> dict[str, str]:
    """Return workload_id, sentinel_id, project, phase (may be empty strings)."""
    agent = body.get("agentInfo") if isinstance(body.get("agentInfo"), dict) else {}
    manifest = (
        agent.get("agentManifest") if isinstance(agent.get("agentManifest"), dict) else {}
    )
    attrs = body.get("attributes") if isinstance(body.get("attributes"), dict) else {}

    sentinel_id = (
        _walk_str(body, ("sentinel_id", "agentIdentifier", "identifier"))
        or _walk_str(agent, ("identifier",))
        or _walk_str(manifest, ("identifier",))
    )
    workload_id = (
        _walk_str(body, ("workload_id", "workloadId"))
        or _walk_str(attrs, ("workload_id", "federation.workload_id"))
        or _walk_str(agent, ("workload_id",))
        or sentinel_id
    )
    project = (
        _walk_str(body, ("project", "federation.project"))
        or _walk_str(attrs, ("project", "federation.project"))
        or "signals"
    )
    phase = (
        _walk_str(body, ("phase", "federation.phase"))
        or _walk_str(attrs, ("phase", "federation.phase"))
        or "running"
    ).lower()
    return {
        "workload_id": workload_id,
        "sentinel_id": sentinel_id,
        "project": project,
        "phase": phase,
    }
