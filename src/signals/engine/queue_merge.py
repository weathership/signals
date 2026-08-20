"""Merge peer QueueHint lists into federation-queues.yaml (additive).

Signals is SoR. Peers never call YK REST. Empty hints are ignored.
"""

from __future__ import annotations

from typing import Any


def merge_queue_hints(doc: dict[str, Any], hints: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Insert missing inference leaves. Does not delete or shrink existing leaves."""
    added: list[str] = []
    inference = _find_named(doc, "inference")
    if inference is None:
        return doc, added
    children = inference.setdefault("queues", [])
    by_name = {q.get("name"): q for q in children if isinstance(q, dict)}
    for hint in hints:
        path = str(hint.get("path") or "")
        name = path.rsplit(".", 1)[-1] if path else ""
        if not name or name in by_name:
            continue
        leaf: dict[str, Any] = {
            "name": name,
            "submitacl": "*",
            "properties": {
                "federation.class": str(hint.get("resource_class") or f"internal.inference.{name}"),
                "federation.examples": str(hint.get("examples") or ""),
            },
            "resources": {
                "guaranteed": {
                    "federation.zndx.org/gpu": str(int(hint.get("gpu_guarantee") or 0)),
                },
                "max": {
                    "federation.zndx.org/gpu": str(int(hint.get("gpu_max") or hint.get("gpu_guarantee") or 0)),
                },
            },
            "maxapplications": int(hint.get("max_applications") or 1),
        }
        policy = str(hint.get("preemption_policy") or "").strip()
        if policy:
            leaf["properties"]["preemption.policy"] = policy
        delay = str(hint.get("preemption_delay") or "").strip()
        if delay:
            leaf["properties"]["preemption.delay"] = delay
        children.append(leaf)
        by_name[name] = leaf
        added.append(path or name)
    return doc, added


def _find_named(node: Any, name: str) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if node.get("name") == name and "queues" in node:
            return node
        for key in ("partitions", "queues"):
            kids = node.get(key)
            if isinstance(kids, list):
                for child in kids:
                    found = _find_named(child, name)
                    if found is not None:
                        return found
    elif isinstance(node, list):
        for child in node:
            found = _find_named(child, name)
            if found is not None:
                return found
    return None
