"""kubectl + YK REST used by ops probes. Not a product client."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests


def pick_kubeconfig() -> str:
    for c in (
        os.environ.get("KUBECONFIG") or "",
        str(Path.home() / ".kube" / "rke2.yaml"),
        str(Path.home() / ".kube" / "config"),
        "/etc/rancher/rke2/rke2.yaml",
    ):
        if c and Path(c).is_file() and os.access(c, os.R_OK):
            return c
    return str(Path.home() / ".kube" / "rke2.yaml")


def kubectl(*args: str, kubeconfig: str | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("kubectl")
    if not exe:
        raise RuntimeError("kubectl not found")
    kc = kubeconfig or pick_kubeconfig()
    cmd = [exe, "--kubeconfig", kc, *args]
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def yk_app_state(app_id: str, yk_url: str) -> str:
    url = f"{yk_url.rstrip('/')}/ws/v1/partition/default/application/{app_id}"
    try:
        r = requests.get(url, timeout=5)
    except requests.RequestException:
        return "UNKNOWN"
    if r.status_code == 404:
        return "MISSING"
    if r.status_code != 200 or not r.content:
        return "UNKNOWN"
    try:
        data = r.json()
    except ValueError:
        return "UNKNOWN"
    if not isinstance(data, dict):
        return "UNKNOWN"
    return str(data.get("applicationState") or data.get("state") or "UNKNOWN")


def yk_queue_apps(queue: str, yk_url: str) -> list[dict[str, Any]]:
    url = f"{yk_url.rstrip('/')}/ws/v1/partition/default/queue/{queue}/applications"
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return []
    return data if isinstance(data, list) else []
