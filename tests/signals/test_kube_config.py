"""Readable kubeconfig pick must include the synced user copy."""

from pathlib import Path

from signals.ops.kube import pick_kubeconfig


def test_pick_kubeconfig_uses_config_kube_when_env_is_unreadable(
    tmp_path, monkeypatch
):
    cfg = tmp_path / ".config" / "kube" / "rke2.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("apiVersion: v1\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KUBECONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert pick_kubeconfig() == str(cfg)
