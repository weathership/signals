"""RequestQueueShare persist + leftover GPU merge (parent max 6).

Contract: ingest returns RECORDED immediately (apply is off the RPC hot
path — the 2026-08-26 admission failure); the coalescing applier promotes
scratch and flips merged records to APPLIED. Tests wait for the flip.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2
from signals.engine.queue_share import (
    GURU_SHAREFAIL,
    GPU,
    PARENT_GPU_MAX,
    QueueShareService,
    QueueShareStore,
    baseline_guarantees,
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


def _svc(tmp: Path):
    svc = QueueShareService(QueueShareStore(tmp / "shares"))
    state: dict = {"yaml": BASE, "applied": 0}

    def read_yaml():
        return state["yaml"]

    def write_scratch(body: str):
        state["yaml"] = body

    def apply_fn():
        state["applied"] += 1

    return svc, state, read_yaml, write_scratch, apply_fn


def _wait_state(svc: QueueShareService, rid: str, want: str = "APPLIED", timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rec = svc.store.get(rid)
        if rec is not None and rec.state == want:
            return rec
        time.sleep(0.02)
    rec = svc.store.get(rid)
    raise AssertionError(f"{rid} is {rec.state if rec else 'missing'}, wanted {want}")


def test_extract_floor_applies_under_parent_max(tmp_path: Path) -> None:
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    req = _req("gaius", GPU_Q["extract"], 1)
    r = svc.ingest(
        req,
        apply_fn=apply_fn,
        read_yaml=read_yaml,
        write_scratch=write_scratch,
    )
    assert r.accepted
    # Off-hot-path contract: RECORDED now, APPLIED once the applier promotes.
    assert r.state == scheduler_pb2.QUEUE_SHARE_RECORDED
    _wait_state(svc, req.request_id, "APPLIED")
    assert state["applied"] >= 1
    assert "federation.zndx.org/gpu: '1'" in state["yaml"] or 'gpu: "1"' in state["yaml"] or "gpu: '1'" in state["yaml"]


def test_same_peer_leaves_coexist_and_overcommit_is_rejected(tmp_path: Path) -> None:
    """(2026-09-04) No implicit supersession ACROSS leaves: a peer's extract
    floor survives its later medium request. The parent max still holds —
    4 + 1 + 2 = 7 > 6, so the medium request is REJECTED, not the extract
    record retired. (Formerly: same-peer SAE superseded extract.)"""
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    kwargs = dict(apply_fn=apply_fn, read_yaml=read_yaml, write_scratch=write_scratch)
    ra = _req("gaius", GPU_Q["heavy"], 4)
    assert svc.ingest(ra, **kwargs).state == scheduler_pb2.QUEUE_SHARE_RECORDED
    _wait_state(svc, ra.request_id, "APPLIED")
    rb = _req("gaius", GPU_Q["extract"], 1)
    svc.ingest(rb, **kwargs)
    _wait_state(svc, rb.request_id, "APPLIED")
    rc = _req("gaius", GPU_Q["medium"], 2)
    c = svc.ingest(rc, **kwargs)
    assert c.state == scheduler_pb2.QUEUE_SHARE_REJECTED
    listed = svc.list(peer="gaius")
    states = {rec.request.shares[0].queue: rec.state for rec in listed}
    assert states[GPU_Q["extract"]] == "APPLIED"
    assert states[GPU_Q["heavy"]] == "APPLIED"
    assert states[GPU_Q["medium"]] == "REJECTED"
    # A light floor that FITS coexists with the extract floor (4 + 1 + 1 = 6).
    rd = _req("gaius", GPU_Q["light"], 1)
    assert svc.ingest(rd, **kwargs).accepted
    _wait_state(svc, rd.request_id, "APPLIED")
    assert svc.store.get(rb.request_id).state == "APPLIED"


def test_supersede_during_apply_stays_superseded(tmp_path: Path) -> None:
    """A record superseded before its apply lands must never flip to APPLIED."""
    import threading

    svc, state, read_yaml, write_scratch, _ = _svc(tmp_path)
    gate = threading.Event()

    def slow_apply():
        gate.wait(timeout=5.0)
        state["applied"] += 1

    kwargs = dict(apply_fn=slow_apply, read_yaml=read_yaml, write_scratch=write_scratch)
    ra = _req("gaius", GPU_Q["extract"], 1)
    svc.ingest(ra, **kwargs)
    # Supersede ra while its apply is still blocked on the gate: the same
    # (peer, queue, wrk, owner) re-declared — the only implicit supersession
    # left (2026-09-04: leaves coexist; a medium request no longer retires it).
    rb = _req("gaius", GPU_Q["extract"], 1)
    svc.ingest(rb, **kwargs)
    gate.set()
    _wait_state(svc, rb.request_id, "APPLIED")
    rec_a = svc.store.get(ra.request_id)
    assert rec_a is not None and rec_a.state == "SUPERSEDED"


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
    _wait_state(svc, rid, "APPLIED")
    b = svc.ingest(_req("gaius", GPU_Q["extract"], 1, rid=rid), **kwargs)
    assert a.request_id == b.request_id == rid
    # Replay reports the record's current state without re-merging.
    assert b.state == scheduler_pb2.QUEUE_SHARE_APPLIED
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
    body = patch_occupancy(BASE, {GPU_Q["extract"]: 1}, baseline={})
    assert "extract" in body
    assert "guaranteed" in body


def test_patch_never_wipes_declared_floor() -> None:
    """A queue with no active peer floor falls back to its DECLARED floor.

    Zeroing it (pre-2026-08-30) erased the SoR extract floor on every ingest,
    so the promoted config could never match federation-queues.yaml.
    """
    import yaml as _yaml

    declared = {GPU_Q["extract"]: 1, GPU_Q["heavy"]: 4}
    # No active floors at all: declared guarantees must survive.
    body = patch_occupancy(BASE, {}, baseline=declared)
    doc = _yaml.safe_load(body)
    from signals.engine.queue_share import find_queue

    ext = find_queue(doc, GPU_Q["extract"])
    assert ext is not None
    assert ext["resources"]["guaranteed"][GPU] == "1"
    heavy = find_queue(doc, GPU_Q["heavy"])
    assert heavy is not None
    assert heavy["resources"]["guaranteed"][GPU] == "4"
    # An active peer floor above the declared floor wins…
    body2 = patch_occupancy(BASE, {GPU_Q["extract"]: 2}, baseline=declared)
    ext2 = find_queue(_yaml.safe_load(body2), GPU_Q["extract"])
    assert ext2 is not None and ext2["resources"]["guaranteed"][GPU] == "2"
    # …but a lower one never drags the queue below the declared floor.
    body3 = patch_occupancy(BASE, {GPU_Q["extract"]: 0}, baseline=declared)
    ext3 = find_queue(_yaml.safe_load(body3), GPU_Q["extract"])
    assert ext3 is not None and ext3["resources"]["guaranteed"][GPU] == "1"


def test_baseline_guarantees_reads_sor() -> None:
    """The repo SoR declares the extract floor (a30c490) and heavy's 4."""
    floors = baseline_guarantees()
    assert floors[GPU_Q["extract"]] == 1
    assert floors[GPU_Q["heavy"]] == 4
    assert floors[GPU_Q["light"]] == 0
    assert floors[GPU_Q["medium"]] == 0


def test_ingest_churn_preserves_extract_floor(tmp_path: Path) -> None:
    """Peer churn on other queues must never erase the declared extract floor."""
    import yaml as _yaml

    from signals.engine.queue_share import find_queue

    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    kwargs = dict(apply_fn=apply_fn, read_yaml=read_yaml, write_scratch=write_scratch)
    rh = _req("gaius", GPU_Q["heavy"], 4)
    svc.ingest(rh, **kwargs)
    _wait_state(svc, rh.request_id, "APPLIED")
    ext = find_queue(_yaml.safe_load(state["yaml"]), GPU_Q["extract"])
    # The SoR baseline (extract=1) holds even though no peer shares extract.
    assert ext is not None
    assert ext["resources"]["guaranteed"][GPU] == "1"


# ── (2026-09-04) supersession identity is (peer, queue, wrk, owner) ─────────────


def _intent_req(peer: str, queue: str, g: int, *, wrk: str, owner: str = "", floor: int | None = None):
    w = scheduler_pb2.WorkloadIntent(wrk=wrk, queue=queue, applications=1, owner=owner)
    if floor is not None:
        w.floor = floor
    return scheduler_pb2.QueueShareRequest(
        peer=peer, request_id=mint_uuidv7(), reason=f"test {wrk}@{owner}",
        workloads=[w], shares=[_share(queue, g)],
    )


def test_different_declarers_on_one_leaf_coexist(tmp_path: Path) -> None:
    """A probe's floor-0 request must not retire a run's floor-1 intent for a
    SHARED workload on the same leaf — the 06:24 intents_honoured failure."""
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    kw = dict(apply_fn=apply_fn, read_yaml=read_yaml, write_scratch=write_scratch)
    a = _intent_req("gaius", GPU_Q["light"], 1, wrk="embedding", owner="ambient-synthesis-28633", floor=1)
    b = _intent_req("gaius", GPU_Q["light"], 0, wrk="clt-probe", owner="", floor=0)
    c = _intent_req("gaius", GPU_Q["light"], 0, wrk="embedding", owner="clt-skos-admit-1", floor=0)
    for r in (a, b, c):
        assert svc.ingest(r, **kw).accepted
    assert svc.store.get(a.request_id).state != "SUPERSEDED"
    assert svc.store.get(b.request_id).state != "SUPERSEDED"
    assert svc.store.get(c.request_id).state != "SUPERSEDED"
    # A declarer re-stating its own intent replaces its prior record only.
    a2 = _intent_req("gaius", GPU_Q["light"], 1, wrk="embedding", owner="ambient-synthesis-28633", floor=1)
    assert svc.ingest(a2, **kw).accepted
    assert svc.store.get(a.request_id).state == "SUPERSEDED"
    assert svc.store.get(c.request_id).state != "SUPERSEDED"
    assert svc.store.get(b.request_id).state != "SUPERSEDED"


def test_legacy_requests_still_supersede_per_leaf(tmp_path: Path) -> None:
    svc, state, read_yaml, write_scratch, apply_fn = _svc(tmp_path)
    kw = dict(apply_fn=apply_fn, read_yaml=read_yaml, write_scratch=write_scratch)
    x = _req("gaius", GPU_Q["extract"], 1)
    y = _req("gaius", GPU_Q["extract"], 1)
    assert svc.ingest(x, **kw).accepted and svc.ingest(y, **kw).accepted
    assert svc.store.get(x.request_id).state == "SUPERSEDED"
    assert svc.store.get(y.request_id).state != "SUPERSEDED"
