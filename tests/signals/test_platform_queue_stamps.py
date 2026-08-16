"""Owned K8s product workloads stamp provided placement onto root.platform."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AF = ROOT / "config" / "k8s" / "airflow" / "values-signals.yaml"
MF = ROOT / "config" / "k8s" / "metaflow" / "deployment.yaml"
EV = ROOT / "config" / "k8s" / "eventing" / "sink-deployment.yaml"
JUST = ROOT / "Justfile"


def _docs(path: Path) -> list[dict]:
    return list(yaml.safe_load_all(path.read_text(encoding="utf-8")))


def test_justfile_has_redeploy() -> None:
    text = JUST.read_text(encoding="utf-8")
    assert "\nredeploy" in text
    assert "python -m signals.ops redeploy" in text


def test_airflow_provided_platform() -> None:
    data = yaml.safe_load(AF.read_text(encoding="utf-8"))
    labels = data["labels"]
    anns = data["airflowPodAnnotations"]
    assert labels["yunikorn.apache.org/queue"] == "root.platform"
    assert labels["applicationId"] == "yunikorn-airflow-platform"
    assert anns["yunikorn.apache.org/queue"] == "root.platform"
    assert anns["yunikorn.apache.org/app-id"] == "yunikorn-airflow-platform"


def test_metaflow_provided_platform() -> None:
    docs = [d for d in _docs(MF) if d and d.get("kind") == "Deployment"]
    assert docs
    meta = docs[0]["spec"]["template"]["metadata"]
    assert meta["annotations"]["yunikorn.apache.org/queue"] == "root.platform"
    assert meta["labels"]["yunikorn.apache.org/queue"] == "root.platform"
    assert meta["labels"]["applicationId"] == "yunikorn-metaflow-platform"


def test_eventing_sink_provided_platform() -> None:
    docs = [d for d in _docs(EV) if d and d.get("kind") == "Deployment"]
    assert docs
    meta = docs[0]["spec"]["template"]["metadata"]
    assert meta["annotations"]["yunikorn.apache.org/queue"] == "root.platform"
    assert meta["labels"]["applicationId"] == "yunikorn-eventing-platform"
