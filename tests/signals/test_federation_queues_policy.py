"""Resource-class federation queues.yaml shape."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

POLICY = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "scheduler"
    / "federation-queues.yaml"
)

GPU = "federation.zndx.org/gpu"

LEAF_CLASSES = {
    "root.default": "default",
    "root.platform": "platform",
    "root.internal.compute": "internal.compute",
    "root.internal.inference.reasoning": "internal.inference.reasoning",
    "root.internal.inference.coding": "internal.inference.coding",
    "root.internal.inference.orchestration": "internal.inference.orchestration",
    "root.internal.inference.instruct": "internal.inference.instruct",
    "root.internal.inference.embedding": "internal.inference.embedding",
    "root.internal.inference.extract": "internal.inference.extract",
    "root.external.token-metered": "external.token-metered",
    "root.external.rate-metered": "external.rate-metered",
    "root.external.subscription.rate-limited": "external.subscription.rate-limited",
}

ZERO_GPU_PREFIXES = (
    "root.default",
    "root.platform",
    "root.internal.compute",
    "root.external",
)

PROP_KEYS = (
    "federation.class",
    "federation.yk_enforces",
    "federation.peer_meters",
    "federation.examples",
)


def _walk(node: dict[str, Any], parent: str) -> list[tuple[str, dict[str, Any]]]:
    name = str(node["name"])
    fqn = name if name == "root" and not parent else f"{parent}.{name}" if parent else name
    out = [(fqn, node)]
    for child in node.get("queues") or []:
        out.extend(_walk(child, fqn))
    return out


def _policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def test_placement_provided_then_default() -> None:
    part = _policy()["partitions"][0]
    rules = part["placementrules"]
    assert [r["name"] for r in rules] == ["provided", "fixed"]
    assert rules[0]["create"] is False
    assert rules[1]["value"] == "root.default"
    assert rules[1]["create"] is False
    assert not any(r.get("value") == "namespace" for r in rules)


def test_no_project_parent_leaves() -> None:
    root = _policy()["partitions"][0]["queues"][0]
    kids = {q["name"] for q in root["queues"]}
    assert kids == {"default", "platform", "internal", "external"}
    assert not {"aegir", "atelier", "gaius", "signals", "hermes"} & kids


def test_leaf_catalog_properties() -> None:
    root = _policy()["partitions"][0]["queues"][0]
    nodes = dict(_walk(root, ""))
    for fqn, cls in LEAF_CLASSES.items():
        q = nodes[fqn]
        assert not q.get("queues"), f"{fqn} must be a leaf"
        props = q["properties"]
        assert props["federation.class"] == cls
        for key in PROP_KEYS:
            assert key in props
            if key != "federation.peer_meters":
                assert str(props[key]).strip()


def test_inference_parent_gpu_pool() -> None:
    root = _policy()["partitions"][0]["queues"][0]
    nodes = dict(_walk(root, ""))
    infer = nodes["root.internal.inference"]
    assert infer["resources"]["max"][GPU] == "6"
    internal = nodes["root.internal"]
    assert internal["resources"]["max"][GPU] == "6"


def test_zero_gpu_outside_inference() -> None:
    root = _policy()["partitions"][0]["queues"][0]
    nodes = dict(_walk(root, ""))
    for fqn, q in nodes.items():
        if not any(fqn == p or fqn.startswith(p + ".") for p in ZERO_GPU_PREFIXES):
            continue
        max_res = (q.get("resources") or {}).get("max") or {}
        if GPU in max_res:
            assert str(max_res[GPU]) == "0", f"{fqn} must not take GPU"


def test_inference_leaves_share_parent_gpu() -> None:
    root = _policy()["partitions"][0]["queues"][0]
    nodes = dict(_walk(root, ""))
    for fqn in LEAF_CLASSES:
        if not fqn.startswith("root.internal.inference."):
            continue
        max_res = (nodes[fqn].get("resources") or {}).get("max") or {}
        assert GPU not in max_res, f"{fqn} should inherit parent GPU max"
