"""PromoteScratch servicer path (mocked YK + apply)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from signals.engine.k8s_apply import ApplyConfig, ApplyResult
from signals.engine.projection import ProjectionStore
from signals.engine.servicers.scheduler import SchedulerServicer
from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2


def _servicer(tmp: Path, apply_enabled: bool = True) -> SchedulerServicer:
    store = ProjectionStore(tmp)
    yaml_body = """partitions:
  - name: default
    queues:
      - name: root
        submitacl: '*'
"""
    store.write_config(yaml_body, root="scratch")
    store.write_config(yaml_body, root="current")
    yk = MagicMock()
    yk.validate_conf.return_value = (True, "ok")
    yk.queue_tree.return_value = {
        "queuename": "root",
        "status": "Active",
        "isLeaf": True,
        "children": [],
    }
    apply_cfg = ApplyConfig(enabled=apply_enabled)
    return SchedulerServicer(yk, store, apply_cfg=apply_cfg)


def test_promote_dry_run_no_archive(tmp_path: Path):
    svc = _servicer(tmp_path)
    with patch(
        "signals.engine.servicers.scheduler.apply_queues_yaml",
        return_value=ApplyResult(ok=True, message="dry-run ok", dry_run=True),
    ) as apply:
        r = svc.PromoteScratch(
            scheduler_pb2.PromoteScratchRequest(dry_run=True), context=None
        )
    assert r.ok
    assert not r.applied
    apply.assert_called_once()
    stamps = [p for p in (tmp_path / "archive").iterdir() if p.is_dir() and p.name not in ("config", "queues")]
    assert stamps == []


def test_promote_apply_then_archive(tmp_path: Path):
    svc = _servicer(tmp_path)
    with patch(
        "signals.engine.servicers.scheduler.apply_queues_yaml",
        return_value=ApplyResult(
            ok=True,
            message="applied → yunikorn/yunikorn-configs",
            target="yunikorn/yunikorn-configs",
        ),
    ):
        r = svc.PromoteScratch(
            scheduler_pb2.PromoteScratchRequest(dry_run=False, archive_stamp="t1"),
            context=None,
        )
    assert r.ok
    assert r.applied
    assert r.archive_id == "t1"
    assert (tmp_path / "archive" / "t1" / "config" / "queues.yaml").is_file()


def test_promote_apply_failure_leaves_projection(tmp_path: Path):
    from signals.engine.k8s_apply import ApplyError

    svc = _servicer(tmp_path)
    before = (tmp_path / "current" / "config" / "queues.yaml").read_text()
    with patch(
        "signals.engine.servicers.scheduler.apply_queues_yaml",
        side_effect=ApplyError("boom"),
    ):
        r = svc.PromoteScratch(
            scheduler_pb2.PromoteScratchRequest(dry_run=False), context=None
        )
    assert not r.ok
    assert not r.applied
    assert "boom" in r.message
    assert (tmp_path / "current" / "config" / "queues.yaml").read_text() == before
    stamps = [p for p in (tmp_path / "archive").iterdir() if p.is_dir() and p.name not in ("config", "queues")]
    assert stamps == []


def test_promote_apply_disabled_still_local(tmp_path: Path):
    svc = _servicer(tmp_path, apply_enabled=False)
    with patch("signals.engine.servicers.scheduler.apply_queues_yaml") as apply:
        r = svc.PromoteScratch(
            scheduler_pb2.PromoteScratchRequest(dry_run=False, archive_stamp="t2"),
            context=None,
        )
    apply.assert_not_called()
    assert r.ok
    assert not r.applied
    assert r.archive_id == "t2"
