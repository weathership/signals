"""Peer WRK occupancy intent: persist, merge leftover floors, apply via PromoteScratch.

Peers never write queues.yaml. YK preemption only fires under guarantee.
Parent GPU max is 6: standing heavy (4) + leftover pair (extract vs light/CLT
or medium/SAE).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.protobuf.json_format import MessageToDict, ParseDict

from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2
from signals.uuidv7 import is_uuidv7

log = logging.getLogger("signals.engine.queue_share")

GURU_SHAREFAIL = "#YK.00000007.SHAREFAIL"
GPU = "federation.zndx.org/gpu"
# (2026-09-04) ListQueueShareRequests limit 0 = backend default (wire contract);
# unbounded lists over a growing store saturated the servicer. Terminal
# (SUPERSEDED / REJECTED) records are pruned past this horizon; live ones never.
DEFAULT_LIST_LIMIT = 500
PRUNE_HORIZON_S = 24 * 3600
PARENT_GPU_MAX = 6
# 2026-09-06: hermes added — its engine declares the interactive agent-rtc
# session as a coordination Activity (and may request queue shares).
ALLOWED_PEERS = frozenset({"gaius", "aegir", "atelier", "signals", "hermes"})
# Leftover pair beside standing thinking (4). Mutually exclusive floors.
LEFTOVER_QUEUES = frozenset(
    {
        "root.internal.inference.extract",
        "root.internal.inference.light",
        "root.internal.inference.medium",
    }
)
# (2026-09-07) agent-rtc joins the share-managed leaves: its guarantee is no
# longer a standing SoR floor but the Hermes interactive_session Activity's
# claim, asserted by the arbiter only while the session RUNS (user: "agent-rtc
# would only be configured whenever the interactive WebRTC workload is
# active, per Hermes and Airflow"). patch_occupancy writes max(declared 0,
# asserted floor) so the leaf reads 1 during a session and 0 otherwise.
OCCUPANCY_QUEUES = LEFTOVER_QUEUES | {
    "root.internal.inference.heavy",
    "root.internal.inference.agent-rtc",
}
# Repo-anchored: the engine's cwd is not guaranteed (systemd vs devenv vs CLI).
BASELINE = Path(
    os.environ.get(
        "SIGNALS_YK_BASELINE",
        str(Path(__file__).resolve().parents[3] / "config/scheduler/federation-queues.yaml"),
    )
)

_STATES = {
    "RECORDED": scheduler_pb2.QUEUE_SHARE_RECORDED,
    "SUPERSEDED": scheduler_pb2.QUEUE_SHARE_SUPERSEDED,
    "APPLIED": scheduler_pb2.QUEUE_SHARE_APPLIED,
    "REJECTED": scheduler_pb2.QUEUE_SHARE_REJECTED,
    # Batch taken by the applier; kubectl apply in flight. Peers read this as
    # progress. Older bindings without the name still see the wire value (5).
    "APPLYING": getattr(scheduler_pb2, "QUEUE_SHARE_APPLYING", 5),
}

# States that still count toward the merged floors (the record is live).
_LIVE = frozenset({"RECORDED", "APPLYING", "APPLIED"})


class SharePersistError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"{GURU_SHAREFAIL} {detail}")


@dataclass
class ShareRecord:
    request: scheduler_pb2.QueueShareRequest
    recorded_at_ns: int
    state: str  # RECORDED | APPLYING | SUPERSEDED | APPLIED | REJECTED
    # Apply outcome (peers score the arbiter from these).
    applied_at_ns: int = 0
    apply_ms: int = 0
    apply_error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "request": MessageToDict(self.request, preserving_proto_field_name=True),
            "recorded_at_ns": self.recorded_at_ns,
            "state": self.state,
            "applied_at_ns": self.applied_at_ns,
            "apply_ms": self.apply_ms,
            "apply_error": self.apply_error,
        }

    @classmethod
    def from_json(cls, doc: dict[str, Any]) -> "ShareRecord":
        req = scheduler_pb2.QueueShareRequest()
        ParseDict(doc.get("request") or {}, req, ignore_unknown_fields=True)
        return cls(
            request=req,
            recorded_at_ns=int(doc.get("recorded_at_ns") or 0),
            state=str(doc.get("state") or "RECORDED"),
            applied_at_ns=int(doc.get("applied_at_ns") or 0),
            apply_ms=int(doc.get("apply_ms") or 0),
            apply_error=str(doc.get("apply_error") or ""),
        )


class QueueShareStore:
    """One JSON file per record (the durable log) behind an in-memory index.

    (2026-09-04) ``list_all`` used to re-read every file on every call. With
    ~2000 mostly-SUPERSEDED records a list took ~3.6 s; peers polling every
    3 s with a 1.5 s deadline timed out client-side while this server kept
    reading for the abandoned call, the Scheduler's thread pool saturated and
    RequestQueueShare starved too (gaius deferrals after its 600 s net,
    06:00–06:12). Reads now come from the index; files are written through.
    ``prune`` retires terminal records past a horizon so the set stays small.
    """

    TERMINAL_STATES = ("SUPERSEDED", "REJECTED")

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._mu = threading.Lock()
        self._index: dict[str, ShareRecord] | None = None  # loaded on first use

    def _path(self, request_id: str) -> Path:
        safe = request_id.replace("/", "_")
        return self.root / f"{safe}.json"

    def _load_index(self) -> dict[str, ShareRecord]:
        idx: dict[str, ShareRecord] = {}
        for p in self.root.glob("*.json"):
            if p.name.endswith(".tmp"):
                continue
            try:
                rec = ShareRecord.from_json(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            idx[rec.request.request_id] = rec
        log.info("queue share store indexed %d record(s) from %s", len(idx), self.root)
        return idx

    def _ensure_index(self) -> dict[str, ShareRecord]:
        # Caller holds self._mu.
        if self._index is None:
            self._index = self._load_index()
        return self._index

    def get(self, request_id: str) -> ShareRecord | None:
        with self._mu:
            return self._ensure_index().get(request_id)

    def put(self, rec: ShareRecord) -> None:
        rid = rec.request.request_id
        p = self._path(rid)
        tmp = p.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(rec.to_json(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, p)
        except OSError as e:
            raise SharePersistError(f"cannot persist {rid}: {e}") from e
        with self._mu:
            self._ensure_index()[rid] = rec

    def list_all(self) -> list[ShareRecord]:
        with self._mu:
            out = list(self._ensure_index().values())
        out.sort(key=lambda r: (r.recorded_at_ns, r.request.request_id))
        return out

    def prune(self, *, older_than_ns: int, states: tuple[str, ...] = TERMINAL_STATES) -> int:
        """Delete terminal records recorded before ``older_than_ns``. Live
        (APPLIED / RECORDED / APPLYING) records are never pruned — an APPLIED
        record with valid_until 0 is a standing floor until superseded."""
        with self._mu:
            idx = self._ensure_index()
            victims = [
                rid for rid, r in idx.items()
                if r.state in states and r.recorded_at_ns < older_than_ns
            ]
            for rid in victims:
                idx.pop(rid, None)
                try:
                    self._path(rid).unlink(missing_ok=True)
                except OSError as e:  # noqa: PERF203 - one bad unlink must not stop the sweep
                    log.warning("queue share prune: cannot unlink %s: %s", rid, e)
        if victims:
            log.info("queue share store pruned %d terminal record(s) older than horizon", len(victims))
        return len(victims)


def _intent_keys(req: scheduler_pb2.QueueShareRequest) -> set[tuple[str, str, str]]:
    """(queue, wrk, owner) identities a request declares. A request with no
    workloads[] (legacy) is keyed by its queues alone with empty wrk/owner, so
    legacy requests still supersede each other per leaf."""
    queues = {s.queue for s in req.shares}
    if not req.workloads:
        return {(q, "", "") for q in queues}
    keys: set[tuple[str, str, str]] = set()
    for w in req.workloads:
        wrk = (w.wrk or "").strip()
        owner = (getattr(w, "owner", "") or "").strip()
        for q in ({w.queue} if w.queue else queues):
            keys.add((q, wrk, owner))
    return keys


def gpu_qty(share: scheduler_pb2.QueueShare, field: str) -> int:
    m = share.guaranteed if field == "guaranteed" else share.max
    return int((m.quantities or {}).get(GPU, 0) or 0)


def _in_window(req: scheduler_pb2.QueueShareRequest, now_ns: int) -> bool:
    start = int(req.valid_from_ns or 0)
    end = int(req.valid_until_ns or 0)
    if start and now_ns < start:
        return False
    if end and now_ns >= end:
        return False
    return True


def active_records(store: QueueShareStore, now_ns: int | None = None) -> list[ShareRecord]:
    now = now_ns if now_ns is not None else time.time_ns()
    out = []
    for rec in store.list_all():
        if rec.state not in _LIVE:
            continue
        if _in_window(rec.request, now):
            out.append(rec)
    return out


def merge_floors(records: list[ShareRecord]) -> dict[str, int]:
    """Per-queue guaranteed GPU floor across the federated view of active intents.

    The authoritative source is each WorkloadIntent's typed
    requirements.footprint.gpu — the Signals engine sizes YuniKorn queues from the
    real footprints peers advertise, so a changing workload profile (e.g. Metaflow
    churn) reconciles guarantees automatically. The caller's QueueShare.guaranteed
    is a fallback for intents that do not yet carry a footprint (transition).
    """
    # Per record, the EFFECTIVE floor for a queue is: the declared floor
    # (zndx.supervision.v1.ResourceIntent carried as WorkloadIntent.floor,
    # 2026-09-04) when the intent declares one; else the footprint (legacy
    # "authoritative"); else the caller's QueueShare.guaranteed (transition).
    # Per queue, the merged floor is the MAX across live records — a declared
    # 0 ("fully preemptible") lowers only the declaring WRK's contribution;
    # a legacy holder keeps its protection until it migrates to intents.
    # Before floors were declared, guaranteed = tokens at admit protected a
    # probe's occupancy against the run that actually needed the GPU.
    floors: dict[str, int] = {}
    for rec in records:
        per_rec: dict[str, int] = {}
        for sh in rec.request.shares:
            q = (sh.queue or "").strip()
            if q:
                per_rec[q] = max(per_rec.get(q, 0), gpu_qty(sh, "guaranteed"))
        for wi in rec.request.workloads:
            q = (wi.queue or "").strip()
            if not q:
                continue
            # `floor` is proto3 `optional`: presence distinguishes a DECLARED 0
            # from a legacy intent that never set it.
            try:
                declared_floor = wi.HasField("floor")
            except ValueError:  # bindings older than the field
                declared_floor = False
            if declared_floor:
                per_rec[q] = int(wi.floor)  # declared: overrides this record's share/footprint
                continue
            gpu = int(wi.requirements.footprint.gpu or 0)
            if gpu:
                per_rec[q] = gpu          # legacy footprint wins over the share guarantee
        for q, v in per_rec.items():
            floors[q] = max(floors.get(q, 0), v)
    return floors


def occupancy_sum(floors: dict[str, int]) -> int:
    return sum(int(floors.get(q, 0) or 0) for q in OCCUPANCY_QUEUES)


INFERENCE_PARENT = "root.internal.inference"
HEAVY_QUEUE = "root.internal.inference.heavy"


def parent_budget(yaml_body: str | None, floors: dict[str, int]) -> tuple[int, int]:
    """(guaranteed GPU the inference parent's children carry AFTER patch_occupancy,
    the parent's max) — computed the way YuniKorn validates it.

    2026-09-06: the arbiter summed only the share-managed leaves
    (OCCUPANCY_QUEUES) against PARENT_GPU_MAX while the SoR had grown a leaf it
    does not manage — agent-rtc, guaranteed 1 for the Hermes interactive
    session. Merges passed the arbiter at 6, YuniKorn saw 7, every apply batch
    failed validation, nothing ever reached APPLIED, and every gaius thinking
    preload sat out its full 600 s wait-for-APPLIED net (23:37→23:47 UTC).
    Count EVERY child as declared in the config being patched, raised by the
    merged floor where the share system manages the leaf.
    """
    import yaml

    body = yaml_body if yaml_body is not None else baseline_yaml()
    doc = yaml.safe_load(body) or {}
    parent = find_queue(doc, INFERENCE_PARENT)
    if parent is None:
        return occupancy_sum(floors), PARENT_GPU_MAX
    pmax_raw = ((parent.get("resources") or {}).get("max") or {}).get(GPU)
    parent_max = int(pmax_raw) if pmax_raw not in (None, "") else PARENT_GPU_MAX
    total = 0
    for child in parent.get("queues") or []:
        if not isinstance(child, dict) or not child.get("name"):
            continue
        fqn = f"{INFERENCE_PARENT}.{child['name']}"
        declared = int((((child.get("resources") or {}).get("guaranteed") or {}).get(GPU, 0)) or 0)
        if fqn in OCCUPANCY_QUEUES:
            total += max(declared, int(floors.get(fqn, 0) or 0))
        else:
            total += declared
    return total, parent_max


GURU_NOCAPACITY = "#YK.00000013.NOCAPACITY"


def partition_budget(
    yaml_body: str | None,
    floors: dict[str, int],
    baseline: dict[str, int] | None = None,
) -> tuple[int, list[str]]:
    """(Σ leaf guaranteed GPU over the WHOLE partition after patch_occupancy,
    parent over-commits as YuniKorn would report them).

    The invariant the federation owns (user, 2026-09-07): our workloads,
    coordinated or otherwise, must never demand more guaranteed GPUs than the
    system physically has — we push these configurations into YuniKorn, and
    YuniKorn's config validation cannot check them against node capacity.
    Every parent's children are checked against its max (the rule YuniKorn
    does validate).

    Share-managed leaves (OCCUPANCY_QUEUES) count as the SoR's DECLARED floor
    raised by the merged live floor — exactly what patch_occupancy will write.
    NOT the working config's value: that is the PREVIOUS merge, and reading it
    as "declared" double-counted a floor that had already been retired (2026-09-07
    07:40 and 07:51: a stale light/agent-rtc 1 in `current` made the arbiter see
    7 of 6 and shed the interactive session's own claim). Unmanaged leaves count
    as the working config declares them.
    """
    import yaml

    doc = yaml.safe_load(yaml_body if yaml_body is not None else baseline_yaml()) or {}
    declared_sor = baseline if baseline is not None else baseline_guarantees()
    total = 0
    violations: list[str] = []

    def guaranteed(node: dict[str, Any], fqn: str) -> int:
        if fqn in OCCUPANCY_QUEUES:
            return max(int(declared_sor.get(fqn, 0) or 0), int(floors.get(fqn, 0) or 0))
        return int((((node.get("resources") or {}).get("guaranteed") or {}).get(GPU, 0)) or 0)

    def walk(node: dict[str, Any], prefix: str) -> int:
        nonlocal total
        name = str(node.get("name") or "")
        fqn = f"{prefix}.{name}" if prefix else name
        children = [c for c in (node.get("queues") or []) if isinstance(c, dict) and c.get("name")]
        if not children:
            g = guaranteed(node, fqn)
            total += g
            return g
        s = sum(walk(c, fqn) for c in children)
        mx = ((node.get("resources") or {}).get("max") or {}).get(GPU)
        if mx not in (None, "") and s > int(mx):
            violations.append(f"{fqn}: children guaranteed GPU {s} > max {mx}")
        return s

    for part in doc.get("partitions") or []:
        for q in part.get("queues") or []:
            if isinstance(q, dict):
                walk(q, "")
    return total, violations


def capacity_gate(
    yaml_body: str | None,
    floors: dict[str, int],
    capacity: int | None,
    baseline: dict[str, int] | None = None,
) -> str | None:
    """Reason the merged config must NOT be pushed to YuniKorn, or None.

    `capacity` = physical GPUs (the partition's capacity as YuniKorn sees its
    nodes); None = unknown → only the parent-max rule is judged.
    """
    total, violations = partition_budget(yaml_body, floors, baseline)
    reasons = list(violations)
    if capacity is not None and total > int(capacity):
        reasons.append(f"leaf guaranteed GPU {total} > physical GPUs {capacity}")
    return "; ".join(reasons) or None


def find_queue(doc: dict[str, Any], fqn: str) -> dict[str, Any] | None:
    parts = [p for p in fqn.split(".") if p]
    if not parts:
        return None
    nodes = []
    for part in doc.get("partitions") or []:
        nodes.extend(part.get("queues") or [])
    for i, name in enumerate(parts):
        hit = None
        for n in nodes:
            if isinstance(n, dict) and n.get("name") == name:
                hit = n
                break
        if hit is None:
            return None
        if i == len(parts) - 1:
            return hit
        nodes = hit.get("queues") or []
    return None


def baseline_guarantees(yaml_body: str | None = None) -> dict[str, int]:
    """Declared guaranteed GPU floors from the SoR federation-queues.yaml.

    These are standing policy (e.g. extract's floor of 1 so article-curate
    preempts an unguaranteed ask-sae) — peer occupancy can only RAISE a
    queue above its declared floor, never erase it.
    """
    import yaml

    body = yaml_body if yaml_body is not None else baseline_yaml()
    doc = yaml.safe_load(body) or {}
    out: dict[str, int] = {}
    for q in OCCUPANCY_QUEUES:
        node = find_queue(doc, q)
        if node is None:
            continue
        g = (node.get("resources") or {}).get("guaranteed") or {}
        out[q] = int(g.get(GPU, 0) or 0)
    return out


def patch_occupancy(
    yaml_body: str,
    floors: dict[str, int],
    *,
    shares: list[scheduler_pb2.QueueShare] | None = None,
    baseline: dict[str, int] | None = None,
) -> str:
    import yaml

    declared = baseline if baseline is not None else baseline_guarantees()
    doc = yaml.safe_load(yaml_body) or {}
    share_by_q = {s.queue: s for s in (shares or []) if s.queue}
    for q in OCCUPANCY_QUEUES:
        node = find_queue(doc, q)
        if node is None:
            continue
        res = node.setdefault("resources", {})
        g = res.setdefault("guaranteed", {})
        # A queue with no active peer floor falls back to its DECLARED floor,
        # never to 0 — zeroing here silently erased the SoR extract floor on
        # every ingest (2026-08-30 finding).
        g[GPU] = str(max(int(declared.get(q, 0) or 0), int(floors.get(q, 0) or 0)))
        mx = res.setdefault("max", {})
        sh = share_by_q.get(q)
        if sh is not None:
            want_max = gpu_qty(sh, "max")
            if want_max:
                mx[GPU] = str(want_max)
            if sh.max_applications:
                node["maxapplications"] = int(sh.max_applications)
        elif GPU not in mx:
            mx[GPU] = g[GPU]
    return yaml.safe_dump(doc, default_flow_style=False, sort_keys=False)


def baseline_yaml(store_cfg: Path | None = None) -> str:
    p = store_cfg or BASELINE
    if p.is_file():
        return p.read_text(encoding="utf-8")
    raise SharePersistError(f"baseline queues missing: {p}")


def leftover_queues_of(req: scheduler_pb2.QueueShareRequest) -> set[str]:
    return {s.queue for s in req.shares if s.queue in LEFTOVER_QUEUES}


class QueueShareService:
    def __init__(self, store: QueueShareStore, capacity_fn=None):
        self.store = store
        # Physical GPU capacity (the YK partition's, as the servicer reads it).
        # None = unknown: only the parent-max rule is judged, with one warning —
        # production always passes the servicer's reader.
        self._capacity_fn = capacity_fn
        self._warned_nocap = False
        self._mu = threading.Lock()
        # Coalescing applier state: one worker, a pending set of record ids
        # whose floors are merged into the current scratch. Thread-per-request
        # plus a flip gated on state==RECORDED made APPLIED unreachable under
        # WRK churn (2758 records, 0 APPLIED on 2026-08-30).
        self._apply_cv = threading.Condition()
        self._apply_pending: set[str] = set()
        self._apply_fn = None
        self._apply_thread: threading.Thread | None = None

    def ingest(
        self,
        req: scheduler_pb2.QueueShareRequest,
        *,
        apply_fn,
        read_yaml,
        write_scratch,
    ) -> scheduler_pb2.QueueShareResponse:
        """Persist then merge+promote. Peers never write queues.yaml."""
        with self._mu:
            return self._ingest_locked(req, apply_fn, read_yaml, write_scratch)

    def _ingest_locked(
        self,
        req: scheduler_pb2.QueueShareRequest,
        apply_fn,
        read_yaml,
        write_scratch,
    ) -> scheduler_pb2.QueueShareResponse:
        peer = (req.peer or "").strip().lower()
        if peer not in ALLOWED_PEERS:
            return scheduler_pb2.QueueShareResponse(
                accepted=False,
                error=f"{GURU_SHAREFAIL} unknown peer {peer!r}",
                state=scheduler_pb2.QUEUE_SHARE_STATE_UNSPECIFIED,
            )
        rid = (req.request_id or "").strip()
        if not is_uuidv7(rid):
            return scheduler_pb2.QueueShareResponse(
                accepted=False,
                request_id=rid,
                error=f"{GURU_SHAREFAIL} request_id MUST be RFC 9562 UUIDv7",
                state=scheduler_pb2.QUEUE_SHARE_STATE_UNSPECIFIED,
            )
        if not req.valid_from_ns:
            req.valid_from_ns = time.time_ns()
        existing = self.store.get(rid)
        if existing is not None:
            return scheduler_pb2.QueueShareResponse(
                accepted=True,
                request_id=rid,
                state=_STATES.get(existing.state, scheduler_pb2.QUEUE_SHARE_RECORDED),
            )
        if not req.shares:
            return scheduler_pb2.QueueShareResponse(
                accepted=False,
                request_id=rid,
                error=f"{GURU_SHAREFAIL} shares[] empty",
            )
        rec = ShareRecord(request=req, recorded_at_ns=time.time_ns(), state="RECORDED")
        self.store.put(rec)

        if req.supersedes_request_id:
            prior = self.store.get(req.supersedes_request_id)
            if prior and prior.state in _LIVE:
                prior.state = "SUPERSEDED"
                self.store.put(prior)
        # (2026-09-04) The "leftover exclusivity" rule is gone: it retired every
        # live intent of the same peer on a DIFFERENT leftover leaf (extract vs
        # light vs medium were once alternatives for the two leftover tokens).
        # With declared floors merged per leaf and YuniKorn arbitrating across
        # leaves by priority, intents on different leaves COEXIST — a prospects
        # run's extract floor must survive the CLT probe's light request (the
        # gaius queue_share_arbitration objective caught it at 10:17: every
        # extract record SUPERSEDED, the run unprotected). Over-commitment is
        # still refused below (merged floors > parent max → REJECTED).
        # (2026-09-04) Implicit supersession is keyed by (peer, queue, wrk, owner),
        # never by (peer, queue) alone: intents from different declarers for the
        # same leaf — or for the same SHARED workload (embedding held for an admit
        # flow and for an ambient run) — coexist and merge (max per leaf). Keyed
        # by leaf, the CLT probe's floor-0 request retired a running flow's
        # floor-1 embedding intent (gaius queue_share_arbitration objective,
        # intents_honoured FAIL, 06:24). A declarer re-stating its intent for a
        # workload replaces its own prior record; ends use supersedes_request_id.
        new_keys = _intent_keys(req)
        for old in self.store.list_all():
            if old.request.request_id == rid:
                continue
            if (old.request.peer or "").strip().lower() != peer:
                continue
            if old.state not in _LIVE:
                continue
            if _intent_keys(old.request) & new_keys:
                old.state = "SUPERSEDED"
                self.store.put(old)

        active = active_records(self.store)
        floors = merge_floors(active)
        # Judge the merge the way YuniKorn will: every child of the inference
        # parent as declared in the config being patched (agent-rtc included),
        # raised by the merged floors on the share-managed leaves.
        yaml_body = read_yaml() or baseline_yaml()
        self._yaml_io = (read_yaml, write_scratch)
        over0 = self._budget_reason(yaml_body, floors)
        if over0:
            # The newcomer is not automatically the culprit (a zero-floor "ended"
            # record arriving while an older floor over-commits): shed by
            # priority, then judge again. Only a newcomer that is itself the
            # shed victim — or an over-commit no shedding can cure (declared
            # SoR floors alone exceed the max / the physical GPUs) — comes back
            # REJECTED, carrying the reason the merge was refused.
            self._shed_core(read_yaml, write_scratch)
            rec_now = self.store.get(rid)
            active = active_records(self.store)
            floors = merge_floors(active)
            over = self._budget_reason(yaml_body, floors)
            if (rec_now is not None and rec_now.state == "REJECTED") or over:
                if rec_now is not None and rec_now.state != "REJECTED":
                    rec_now.state = "REJECTED"
                    rec_now.apply_error = f"over-commit: {over or over0}"[:400]
                    self.store.put(rec_now)
                return scheduler_pb2.QueueShareResponse(
                    accepted=True,
                    request_id=rid,
                    state=scheduler_pb2.QUEUE_SHARE_REJECTED,
                    error=f"guaranteed GPU over-commit — {over or over0}; floors after shed {floors}",
                )
        try:
            patched = patch_occupancy(yaml_body, floors, shares=list(req.shares))
            write_scratch(patched)
        except SharePersistError:
            raise
        except Exception as e:
            rec.state = "RECORDED"
            self.store.put(rec)
            return scheduler_pb2.QueueShareResponse(
                accepted=True,
                request_id=rid,
                state=scheduler_pb2.QUEUE_SHARE_RECORDED,
                error=f"recorded; scratch deferred: {e}",
            )
        # Apply OFF the RPC hot path: a cold YuniKorn REST / kubectl must never time
        # out the caller (the 2026-08-26 admission failure). Footprint-driven sizing
        # is already written to scratch above; the coalescing applier promotes it to
        # YK and flips every record merged into that scratch RECORDED -> APPLIED.
        # Callers positively wait for APPLIED rather than trusting a fast accept.
        self._queue_apply({r.request.request_id for r in active}, apply_fn)
        return scheduler_pb2.QueueShareResponse(
            accepted=True,
            request_id=rid,
            state=scheduler_pb2.QUEUE_SHARE_RECORDED,
        )

    def _queue_apply(self, merged_ids: set[str], apply_fn) -> None:
        """Hand the scratch snapshot's record ids to the coalescing applier."""
        with self._apply_cv:
            self._apply_pending.update(merged_ids)
            self._apply_fn = apply_fn
            if self._apply_thread is None or not self._apply_thread.is_alive():
                self._apply_thread = threading.Thread(
                    target=self._apply_worker, name="qs-apply", daemon=True
                )
                self._apply_thread.start()
            self._apply_cv.notify()

    def _apply_worker(self) -> None:
        """Promote scratch to YK/kubectl; flip merged records to APPLIED.

        One worker drains the pending set: apply_fn re-promotes the CURRENT
        scratch, which already reflects every pending record's merge (scratch
        is cumulative), so a single successful apply covers the whole batch. A
        record superseded before the apply stays SUPERSEDED — the flip only
        touches records still RECORDED. Failures retry with backoff instead of
        deferring forever (pre-2026-08-30 behavior left records RECORDED until
        the next inbound request, i.e. potentially never).
        """
        backoff = 5.0
        while True:
            with self._apply_cv:
                while not self._apply_pending:
                    if not self._apply_cv.wait(timeout=60.0) and not self._apply_pending:
                        return  # idle: exit; the next ingest restarts the worker
                batch = set(self._apply_pending)
                fn = self._apply_fn
            # Progress is visible to peers: RECORDED -> APPLYING for the batch
            # before the backend apply starts. A peer waiting for APPLIED resets
            # its patience on this transition instead of timing out.
            with self._mu:
                for rid in sorted(batch):
                    r = self.store.get(rid)
                    if r is not None and r.state == "RECORDED":
                        r.state = "APPLYING"
                        self.store.put(r)
            t0 = time.monotonic()
            try:
                result = fn() if fn is not None else None
            except Exception as e:  # noqa: BLE001 - deliberate: never crash the applier
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                log.warning(
                    "queue share apply FAILED after %d ms (%d record(s), retry in %.0fs): %s",
                    elapsed_ms, len(batch), backoff, e,
                )
                with self._mu:
                    for rid in sorted(batch):
                        r = self.store.get(rid)
                        if r is not None and r.state == "APPLYING":
                            r.state = "RECORDED"
                            r.apply_error = str(e)[:400]
                            self.store.put(r)
                # Converge instead of retrying the same over-commit forever
                # (2026-09-06: "validation failed" every 5→300 s for hours while
                # peers waited their nets): retire the floors that over-commit
                # the parent, rewrite scratch from the survivors, retry now.
                shed = self._shed_overcommit()
                if shed:
                    log.warning(
                        "queue share apply: shed %d over-committing record(s) → REJECTED: %s; retrying now",
                        len(shed), ", ".join(shed),
                    )
                    backoff = 5.0
                    continue
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 300.0)
                continue
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            backoff = 5.0
            applied_at = time.time_ns()
            with self._mu:
                for rid in sorted(batch):
                    r = self.store.get(rid)
                    if r is not None and r.state == "APPLYING":
                        r.state = "APPLIED"
                        r.applied_at_ns = applied_at
                        r.apply_ms = elapsed_ms
                        r.apply_error = ""
                        self.store.put(r)
            # The success path was silent before 2026-09-04: a two-minute apply
            # and a backoff cycle were indistinguishable from outside.
            log.info(
                "queue share apply OK: %d record(s) APPLIED in %d ms%s",
                len(batch), elapsed_ms,
                f" — {getattr(result, 'message', '')}" if getattr(result, "message", "") else "",
            )
            try:
                self.store.prune(older_than_ns=time.time_ns() - PRUNE_HORIZON_S * 1_000_000_000)
            except Exception as e:  # noqa: BLE001 - housekeeping never fails an apply
                log.warning("queue share prune skipped: %s", e)
            with self._apply_cv:
                self._apply_pending.difference_update(batch)

    def _shed_overcommit(self) -> list[str]:
        """After a failed apply, retire the floors that over-commit the parent.

        Victims: live records contributing a floor > 0 on a share-managed leaf
        other than heavy (the standing 27B), lowest WorkloadIntent.priority
        first (0 = unspecified = lowest), newest first within a priority. Each
        becomes REJECTED with the reason in apply_error (peers waiting on it
        end their wait at once — REJECTED is terminal on the wire), and scratch
        is rewritten from the survivors so the retry can validate. Returns the
        rejected request_ids. Never raises.
        """
        io = getattr(self, "_yaml_io", None)
        if io is None:
            return []
        read_yaml, write_scratch = io
        with self._mu:
            return self._shed_core(read_yaml, write_scratch)

    def resume(self, *, apply_fn, read_yaml, write_scratch) -> int:
        """Re-queue records left RECORDED/APPLYING by a previous engine process.

        2026-09-06: the applier's pending set is in-memory, so after an engine
        restart every live RECORDED record sat unapplied until the next ingest
        happened to arrive — peers waited their nets against a dark applier.
        Called once at servicer construction; returns how many were queued.
        """
        pending = [r for r in active_records(self.store) if r.state in ("RECORDED", "APPLYING")]
        if not pending:
            return 0
        self._yaml_io = (read_yaml, write_scratch)
        try:
            self._shed_core(read_yaml, write_scratch)
            survivors = merge_floors(active_records(self.store))
            write_scratch(patch_occupancy(read_yaml() or baseline_yaml(), survivors))
        except Exception as e:  # noqa: BLE001 — the applier retries; never fail boot on this
            log.warning("queue share resume: scratch rewrite failed: %s", e)
        ids = {r.request.request_id for r in pending if self.store.get(r.request.request_id).state != "REJECTED"}
        if ids:
            self._queue_apply(ids, apply_fn)
        log.info("queue share resume: %d record(s) re-queued for apply after restart", len(ids))
        return len(ids)

    def _physical_capacity(self) -> int | None:
        if self._capacity_fn is None:
            if not self._warned_nocap:
                self._warned_nocap = True
                log.warning(
                    "%s physical GPU capacity unknown to the arbiter — judging parent maxima only",
                    GURU_NOCAPACITY,
                )
            return None
        return int(self._capacity_fn())

    def _budget_reason(self, yaml_body: str | None, floors: dict[str, int]) -> str | None:
        return capacity_gate(yaml_body, floors, self._physical_capacity())

    def _shed_core(self, read_yaml, write_scratch) -> list[str]:
        """Lock-free core of the shed (callers hold `_mu` or are the ingest path)."""
        rejected: list[str] = []
        try:
            while True:
                active = active_records(self.store)
                floors = merge_floors(active)
                over = self._budget_reason(read_yaml() or baseline_yaml(), floors)
                if not over:
                    break
                victims: list[tuple[int, int, ShareRecord]] = []
                for rec in active:
                    per = merge_floors([rec])
                    contributing = [
                        q for q, v in per.items() if q in OCCUPANCY_QUEUES and q != HEAVY_QUEUE and v > 0
                    ]
                    if not contributing:
                        continue
                    # Priority of the intent(s) that carry the contributing floor —
                    # never the record's max: a phase request bundles several
                    # intents (thinking at 100 beside an embedding floor at 40), and
                    # the bundle's max let a batch floor outrank the interactive
                    # session's own claim.
                    prios = [
                        int(w.priority or 0)
                        for w in rec.request.workloads
                        if (w.queue or "").strip() in contributing
                    ]
                    prio = max(prios, default=0)
                    victims.append((prio, -int(rec.recorded_at_ns), rec))
                if not victims:
                    break  # over-commit is declared policy (SoR floors alone exceed the max)
                victims.sort(key=lambda t: (t[0], t[1]))
                victim = victims[0][2]
                victim.state = "REJECTED"
                victim.apply_error = f"shed: {over}; floors {floors}"[:400]
                self.store.put(victim)
                rejected.append(victim.request.request_id)
            if rejected:
                survivors = merge_floors(active_records(self.store))
                write_scratch(patch_occupancy(read_yaml() or baseline_yaml(), survivors))
        except Exception as e:  # noqa: BLE001 — shedding is best effort; the retry loop continues
            log.warning("queue share shed failed: %s", e)
        return rejected

    def list(
        self,
        *,
        peer: str = "",
        queue: str = "",
        since_ns: int = 0,
        limit: int = 0,
    ) -> list[ShareRecord]:
        peer = (peer or "").strip().lower()
        queue = (queue or "").strip()
        # The wire contract says limit 0 = backend default. Unbounded was the
        # default and it is what saturated the servicer; 500 newest covers every
        # live record many times over (a peer's live set is a handful).
        if not limit:
            limit = DEFAULT_LIST_LIMIT
        rows = self.store.list_all()
        out: list[ShareRecord] = []
        for rec in reversed(rows):  # newest first
            if since_ns and rec.recorded_at_ns < since_ns:
                continue
            if peer and (rec.request.peer or "").strip().lower() != peer:
                continue
            if queue and not any(s.queue == queue for s in rec.request.shares):
                continue
            out.append(rec)
            if limit and len(out) >= limit:
                break
        return out
