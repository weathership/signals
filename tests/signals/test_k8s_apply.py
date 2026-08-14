"""Unit tests for ConfigMap apply adapter (mocked kubectl)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from signals.engine.k8s_apply import (
    ApplyConfig,
    ApplyError,
    apply_queues_yaml,
    resolve_target_configmap,
)


def _cm_yaml(name: str = "yunikorn-configs", queues: str = "partitions: []\n") -> str:
    doc = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": "yunikorn",
            "resourceVersion": "123",
            "uid": "abc",
        },
        "data": {
            "admissionController.filtering.enable": "true",
            "queues.yaml": queues,
        },
    }
    return yaml.safe_dump(doc)


def test_apply_disabled_skips_kubectl():
    cfg = ApplyConfig(enabled=False)
    r = apply_queues_yaml("partitions: []\n", cfg)
    assert r.ok
    assert "disabled" in r.message.lower()


def test_apply_patches_queues_and_preserves_other_keys(tmp_path: Path):
    cfg = ApplyConfig(
        enabled=True,
        namespace="yunikorn",
        configmap="yunikorn-configs",
        kubectl="kubectl",
        kubeconfig=str(tmp_path / "kubeconfig"),
    )
    get_out = _cm_yaml()
    apply_cp = MagicMock(returncode=0, stdout="configmap/yunikorn-configs configured\n", stderr="")
    get_cp = MagicMock(returncode=0, stdout=get_out, stderr="")

    def run_side_effect(cmd, **kwargs):
        if "get" in cmd:
            return get_cp
        if "apply" in cmd:
            # capture applied file
            f_idx = cmd.index("-f") + 1
            applied = Path(cmd[f_idx]).read_text(encoding="utf-8")
            doc = yaml.safe_load(applied)
            assert doc["data"]["queues.yaml"].startswith("partitions:")
            assert "NEW" in doc["data"]["queues.yaml"]
            assert doc["data"]["admissionController.filtering.enable"] == "true"
            assert "resourceVersion" not in doc.get("metadata", {})
            assert "--dry-run=server" not in cmd
            return apply_cp
        raise AssertionError(cmd)

    with patch("signals.engine.k8s_apply.shutil.which", return_value="/bin/kubectl"):
        with patch("signals.engine.k8s_apply.subprocess.run", side_effect=run_side_effect):
            r = apply_queues_yaml("partitions:\n  - name: default  # NEW\n", cfg)
    assert r.ok
    assert r.target == "yunikorn/yunikorn-configs"
    assert not r.dry_run


def test_apply_dry_run_flag():
    cfg = ApplyConfig(enabled=True, configmap="yunikorn-configs")
    get_out = _cm_yaml()
    get_cp = MagicMock(returncode=0, stdout=get_out, stderr="")
    apply_cp = MagicMock(
        returncode=0, stdout="configmap/yunikorn-configs configured (server dry run)\n", stderr=""
    )

    def run_side_effect(cmd, **kwargs):
        if "get" in cmd:
            return get_cp
        assert "--dry-run=server" in cmd
        return apply_cp

    with patch("signals.engine.k8s_apply.shutil.which", return_value="/bin/kubectl"):
        with patch("signals.engine.k8s_apply.subprocess.run", side_effect=run_side_effect):
            r = apply_queues_yaml("partitions: []\n", cfg, dry_run=True)
    assert r.ok and r.dry_run


def test_fallback_configmap():
    cfg = ApplyConfig(
        enabled=True,
        configmap="yunikorn-configs",
        fallback_configmap="yunikorn-defaults",
    )
    missing = MagicMock(returncode=1, stdout="", stderr='Error from server (NotFound): configmaps "yunikorn-configs" not found')
    present = MagicMock(returncode=0, stdout=_cm_yaml("yunikorn-defaults"), stderr="")

    calls = {"n": 0}

    def run_side_effect(cmd, **kwargs):
        calls["n"] += 1
        # first get primary fails, second get fallback succeeds (resolve + get)
        joined = " ".join(cmd)
        if "get" in cmd and "yunikorn-configs" in joined:
            return missing
        if "get" in cmd and "yunikorn-defaults" in joined:
            return present
        if "apply" in cmd:
            return MagicMock(returncode=0, stdout="ok", stderr="")
        return missing

    with patch("signals.engine.k8s_apply.shutil.which", return_value="/bin/kubectl"):
        with patch("signals.engine.k8s_apply.subprocess.run", side_effect=run_side_effect):
            name = resolve_target_configmap(cfg)
            assert name == "yunikorn-defaults"
            r = apply_queues_yaml("partitions: []\n", cfg)
    assert r.ok
    assert "yunikorn-defaults" in r.target


def test_apply_failure_raises():
    cfg = ApplyConfig(enabled=True)
    get_cp = MagicMock(returncode=0, stdout=_cm_yaml(), stderr="")
    apply_cp = MagicMock(returncode=1, stdout="", stderr="forbidden")

    def run_side_effect(cmd, **kwargs):
        if "get" in cmd:
            return get_cp
        return apply_cp

    with patch("signals.engine.k8s_apply.shutil.which", return_value="/bin/kubectl"):
        with patch("signals.engine.k8s_apply.subprocess.run", side_effect=run_side_effect):
            with pytest.raises(ApplyError, match="apply"):
                apply_queues_yaml("partitions: []\n", cfg)
