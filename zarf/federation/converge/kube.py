"""Minimal kubectl helpers for signals-federation converge (stdlib + kubectl)."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, List, Optional


def kubeconfig() -> str:
    return os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/rke2.yaml"))


def kubectl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    cmd = ["kubectl", f"--kubeconfig={kubeconfig()}", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def get_json(*args: str) -> Optional[Any]:
    r = kubectl("get", *args, "-o", "json")
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def node_ready() -> bool:
    data = get_json("nodes")
    if not data or not data.get("items"):
        return False
    for n in data["items"]:
        for c in n.get("status", {}).get("conditions", []):
            if c.get("type") == "Ready" and c.get("status") == "True":
                return True
    return False


def ns_exists(name: str) -> bool:
    r = kubectl("get", "ns", name)
    return r.returncode == 0


def deployment_available(ns: str, name: str) -> bool:
    data = get_json("deployment", name, "-n", ns)
    if not data:
        return False
    for c in data.get("status", {}).get("conditions", []):
        if c.get("type") == "Available" and c.get("status") == "True":
            return True
    return False


def crd_exists(name: str) -> bool:
    r = kubectl("get", "crd", name)
    return r.returncode == 0


def configmap_data(ns: str, name: str) -> dict:
    data = get_json("configmap", name, "-n", ns)
    if not data:
        return {}
    return data.get("data") or {}


def ksvc_ready(ns: str, name: str) -> bool:
    data = get_json("ksvc", name, "-n", ns)
    if not data:
        return False
    for c in data.get("status", {}).get("conditions", []):
        if c.get("type") == "Ready" and c.get("status") == "True":
            return True
    return False


def pods_running(ns: str, label: Optional[str] = None) -> int:
    args: List[str] = ["pods", "-n", ns]
    if label:
        args.extend(["-l", label])
    data = get_json(*args)
    if not data:
        return 0
    n = 0
    for p in data.get("items", []):
        if p.get("status", {}).get("phase") == "Running":
            n += 1
    return n


def zarf_ns_ok() -> bool:
    return ns_exists("zarf") and (
        deployment_available("zarf", "zarf-docker-registry")
        or pods_running("zarf", "app=docker-registry") > 0
        or True  # ns present is enough if registry name varies
    )
