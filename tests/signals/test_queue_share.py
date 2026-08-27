"""RequestQueueShare persist + leftover GPU merge (parent max 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2
from signals.engine.queue_share import (
    GURU_SHAREFAIL,
    GPU,
    PARENT_GPU_MAX,
    QueueShareService,
    QueueShareStore,
    occupancy_sum,
    patch_occupancy,
)
from signals.uuidv7 import mint as mint_uuidv7

GPU_Q = {
    "extract": "root.internal.inference.extract",
    "light": "root.internal.inference.light",
    "medium": "root.internal.inference.medium",
    "heavy": "root.internal.inference.heavy",
}

BASE = """
partitions:
  - name: default
    queues:
      - name: root
        queues:
          - name: internal
            queues:
              - name: inference
                resources:
                  max: {federation.zndx.org/gpu: "6"}
                queues:
                  - name: heavy
                    resources:
                      guaranteed: {federation.zndx.org/gpu: "4"}
                      max: {federation.zndx.org/gpu: "4"}
                    maxapplications: 1
                  - name: light
                    resources:
                      guaranteed: {federation.zndx.org/gpu: "0"}
                      max: {federation.zndx.org/gpu: "2"}
                    maxapplications: 2
                  - name: medium
                    resources:
                      guaranteed: {federation.zndx.org/gpu: "0"}
                      max: {federation.zndx.org/gpu: "2"}
                    maxapplications: 1
                  - name: extract
                    resources:
                      guaranteed: {federation.zndx.org/gpu: "0"}
                      max: {federation.zndx.org/gpu: "2"}
                    maxapplications: 2
"""


def _share(queue: str, g: int, mx: int = 0, apps: int = 1) -> scheduler_pb2.QueueShare:
    return scheduler_pb2.QueueShare(
        queue=queue,
        guaranteed=scheduler_pb2.ResourceMap(quantities={GPU: g}),
        max=scheduler_pb2.ResourceMap(quantities={GPU: mx or g or 2}),
        max_applications=apps,
    )


def _req(peer: str, queue: str, g: int, *, rid: str | None = None) -> scheduler_pb2.QueueShareRequest:
    return scheduler_pb2.QueueShareRequest(
        peer=peer,
        request_id=rid or mint_uuidv7(),
        reason=f"test {queue}={g}",
        workloads=[
            scheduler_pb2.WorkloadIntent(
                wrk="article-curate" if "extract" in queue else "optillm",
                queue=queue,
                applications=1,
            )
        ],
        shares=[_share(queue, g)],
    )


def _svc(tmp: Path) -> tuple[QueueShareService, dict]:
    svc = QueueShareService(QueueShareStore(tmp / "shares"))
    state: dict = {"yaml": BASE, "applied": 0}

    def read_yaml():
        return state["yaml"]

    def write_scratch(body: str):
        state["yaml"] = body

    def apply_fn():
        state["applied"] += 1

    return svc, state, read_yaml, write_scratch, apply_fn


def test_extract_floor_applies_under_parent_max(tmp_path: Path) -> None:
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    r = svc.ingest(
        _req("gaius", GPU_Q["extract"], 1),
        apply_fn=apply_fn,
        read_yaml=read_yaml,
        write_scratch=write_scratch,
    )
    assert r.accepted
    assert r.state == scheduler_pb2.QUEUE_SHARE_APPLIED
    assert state["applied"] == 1
    assert "federation.zndx.org/gpu: '1'" in state["yaml"] or 'gpu: "1"' in state["yaml"] or "gpu: '1'" in state["yaml"]


def test_same_peer_leftover_sae_supersedes_extract(tmp_path: Path) -> None:
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    kwargs = dict(apply_fn=apply_fn, read_yaml=read_yaml, write_scratch=write_scratch)
    a = svc.ingest(_req("gaius", GPU_Q["heavy"], 4), **kwargs)
    assert a.state == scheduler_pb2.QUEUE_SHARE_APPLIED
    b = svc.ingest(_req("gaius", GPU_Q["extract"], 1), **kwargs)
    assert b.state == scheduler_pb2.QUEUE_SHARE_APPLIED
    # extract vs medium/SAE leftover: same peer SAE supersedes extract (4+2=6).
    c = svc.ingest(_req("gaius", GPU_Q["medium"], 2), **kwargs)
    assert c.accepted
    assert c.state == scheduler_pb2.QUEUE_SHARE_APPLIED
    listed = svc.list(peer="gaius")
    states = {rec.request.shares[0].queue: rec.state for rec in listed}
    assert states[GPU_Q["extract"]] == "SUPERSEDED"
    assert states[GPU_Q["medium"]] == "APPLIED"


def test_two_peers_overlap_reject(tmp_path: Path) -> None:
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    kwargs = dict(apply_fn=apply_fn, read_yaml=read_yaml, write_scratch=write_scratch)
    svc.ingest(_req("gaius", GPU_Q["heavy"], 4), **kwargs)
    svc.ingest(_req("gaius", GPU_Q["extract"], 1), **kwargs)
    r = svc.ingest(_req("aegir", GPU_Q["medium"], 2), **kwargs)
    assert r.accepted
    assert r.state == scheduler_pb2.QUEUE_SHARE_REJECTED
    assert "exceeds parent max" in r.error
    assert occupancy_sum({GPU_Q["heavy"]: 4, GPU_Q["extract"]: 1, GPU_Q["medium"]: 2}) > PARENT_GPU_MAX


def test_idempotent_uuidv7(tmp_path: Path) -> None:
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    rid = mint_uuidv7()
    kwargs = dict(apply_fn=apply_fn, read_yaml=read_yaml, write_scratch=write_scratch)
    a = svc.ingest(_req("gaius", GPU_Q["extract"], 1, rid=rid), **kwargs)
    b = svc.ingest(_req("gaius", GPU_Q["extract"], 1, rid=rid), **kwargs)
    assert a.request_id == b.request_id == rid
    assert state["applied"] == 1


def test_non_v7_rejected(tmp_path: Path) -> None:
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    r = svc.ingest(
        scheduler_pb2.QueueShareRequest(
            peer="gaius",
            request_id="00000000-0000-4000-8000-000000000001",
            shares=[_share(GPU_Q["extract"], 1)],
        ),
        apply_fn=apply_fn,
        read_yaml=read_yaml,
        write_scratch=write_scratch,
    )
    assert not r.accepted
    assert GURU_SHAREFAIL in r.error
    empty = svc.ingest(
        scheduler_pb2.QueueShareRequest(
            peer="gaius",
            request_id="",
            shares=[_share(GPU_Q["extract"], 1)],
        ),
        apply_fn=apply_fn,
        read_yaml=read_yaml,
        write_scratch=write_scratch,
    )
    assert not empty.accepted
    assert "UUIDv7" in empty.error


def test_persist_fail_guru(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from signals.engine import queue_share as qs

    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)

    def boom(self, rec):
        raise qs.SharePersistError("disk full")

    monkeypatch.setattr(QueueShareStore, "put", boom)
    with pytest.raises(qs.SharePersistError, match="SHAREFAIL"):
        svc.ingest(
            _req("gaius", GPU_Q["extract"], 1),
            apply_fn=apply_fn,
            read_yaml=read_yaml,
            write_scratch=write_scratch,
        )


def test_list_filters(tmp_path: Path) -> None:
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    kwargs = dict(apply_fn=apply_fn, read_yaml=read_yaml, write_scratch=write_scratch)
    svc.ingest(_req("gaius", GPU_Q["extract"], 1), **kwargs)
    svc.ingest(_req("atelier", GPU_Q["light"], 1), **kwargs)
    assert len(svc.list(peer="gaius")) == 1
    assert len(svc.list(queue=GPU_Q["light"])) == 1


def test_patch_does_not_hand_yaml_to_peer() -> None:
    body = patch_occupancy(BASE, {GPU_Q["extract"]: 1})
    assert "extract" in body
    assert "guaranteed" in body
