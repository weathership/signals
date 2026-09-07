"""Workload catalogue — engines SUBMIT their scheduled workloads; Signals materialises them.

User (2026-09-07): "With workloads being synced from every project soon, we need
reliable ordering with associated YK configurations Signals (the engine) can
pick up and apply to YK for the duration of the scheduled active workflow be it
Metaflow or otherwise including the interactive workflow defined today for
agent-rtc from Hermes."

Contract (specification/protocol/coordination_activities.md, "The workload
catalogue"): a peer ENGINE calls ``Scheduler/SyncWorkloads(peer, workloads[],
replace)`` with one ``zndx.engine.v1.ScheduleHint`` per workload — catalogue id,
kind, ``cron`` or ``after`` (catalogue ids it follows), ``claims`` (its YuniKorn
queue configuration), postures, horizon, runner, source, enabled. Signals:

  * persists each peer's entries under ``<projection root>/workloads/<peer>.json``
    (the peer file is the catalogue's truth; a ``replace`` sync is the peer's
    WHOLE catalogue — entries absent from it are kept but PAUSED, history kept);
  * publishes the federation registry to the Airflow Variable ``zndx_workloads``
    (the Airflow-native store for dynamic DAG generation) — only when the
    registry content changed;
  * the dynamic DAG module ``coord_workloads_dag.py`` generates one workload DAG
    per registry entry that has a ``dag_id``: ``cron`` entries are
    time-scheduled, ``after`` entries are Asset-scheduled on the named kinds'
    ended Assets (``zndx.coord.<kind>.ended``) — ``after_mode`` says how:
    ``all`` (default; every named workload ended since the last run) or ``any``
    (any one of them ended — a digest such as a project's agenda brief, refreshed
    whenever a producer finishes); ``cron`` + ``after`` with an ``after_mode`` is
    time OR assets (the digest also rolls over on its clock); disabled entries
    materialise paused; ``source = engine`` entries (the interactive agent-rtc
    workflow) are catalogued for visibility and declared by the engine itself.

Every run of a materialised DAG is an Activity (``coord_signals.make_workload_dag``):
the owner engine runs the class while its lease is heartbeated and Signals
asserts the entry's ``claims`` into the arbiter for exactly that duration.

Fail-fast: a malformed entry is recorded with ``state = error`` and its reason —
never silently dropped, never materialised. Airflow unreachable → the peer file
is still written and the publish is retried on the next sync / boot.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from signals.engine.airflow_api import AirflowClient, AirflowError, GURU_API, GURU_DAGMISSING
from signals.engine.generated.zndx.engine.v1 import engine_pb2
from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2
from signals.engine.queue_share import ALLOWED_PEERS

log = logging.getLogger("signals.engine.workloads_catalog")

GURU_CATALOG = "#CO.0000000B.CATALOG"
GURU_CATALOG_AIRFLOW = "#CO.0000000C.CATALOGAIRFLOW"

VARIABLE_KEY = "zndx_workloads"
VARIABLE_DESCRIPTION = (
    "Federation workload catalogue written by the Signals engine (Scheduler/SyncWorkloads). "
    "Read at parse time by coord_workloads_dag.py — do not edit by hand."
)

STATE_MATERIALIZED = "materialized"
STATE_PAUSED = "paused"
STATE_ENGINE_DECLARED = "engine_declared"
STATE_ERROR = "error"

SOURCE_ENGINE = "engine"

AFTER_MODE_ALL = "all"
AFTER_MODE_ANY = "any"
AFTER_MODES = frozenset({AFTER_MODE_ALL, AFTER_MODE_ANY})


def _now_ns() -> int:
    return time.time_ns()


class CatalogError(RuntimeError):
    def __init__(self, guru: str, msg: str):
        self.guru = guru
        super().__init__(f"{guru} {msg}")


@dataclass
class CatalogEntry:
    peer: str
    id: str
    kind: str
    dag_id: str = ""
    cron: str = ""
    timezone: str = ""
    after: list[str] = field(default_factory=list)          # catalogue ids this follows
    after_kinds: list[str] = field(default_factory=list)    # resolved kinds (the ended Assets)
    # ScheduleHint.after_mode (protocol ce31d5d): "" → all (Airflow AssetAll: every
    # named workload ended since the last run); "any" → AssetAny (any one of them
    # ended — a digest such as a project's agenda brief). With `cron` as well the
    # schedule is time OR assets (AssetOrTimeSchedule).
    after_mode: str = ""
    claims: list[dict[str, Any]] = field(default_factory=list)
    precludes: list[str] = field(default_factory=list)
    postures: dict[str, str] = field(default_factory=dict)
    horizon_s: int = 0
    runner: str = ""
    source: str = ""
    enabled: bool = True
    description: str = ""
    engine_build: str = ""
    synced_ns: int = 0
    state: str = STATE_MATERIALIZED
    error: str = ""

    # ── wire ↔ record ────────────────────────────────────────────────────────
    @classmethod
    def from_hint(
        cls, peer: str, hint: engine_pb2.ScheduleHint, *, engine_build: str, now_ns: int
    ) -> "CatalogEntry":
        return cls(
            peer=peer,
            id=(hint.id or "").strip(),
            kind=(hint.kind or "").strip(),
            dag_id=(hint.airflow_dag_id or "").strip(),
            cron=(hint.cron or "").strip(),
            timezone=(hint.timezone or "").strip(),
            after=[a.strip() for a in hint.after if a.strip()],
            after_mode=(hint.after_mode or "").strip().lower(),
            claims=[{"leaf": c.leaf, "gpu": int(c.gpu)} for c in hint.claims],
            precludes=[p for p in hint.precludes if p],
            postures=dict(hint.postures),
            horizon_s=int(hint.horizon_s or 0),
            runner=(hint.runner or "").strip(),
            source=(hint.source or "").strip(),
            enabled=bool(hint.enabled),
            description=(hint.description or "").strip(),
            engine_build=engine_build or "",
            synced_ns=now_ns,
        )

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "CatalogEntry":
        known = {f for f in cls.__dataclass_fields__}  # noqa: SLF001
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def to_hint(self) -> engine_pb2.ScheduleHint:
        h = engine_pb2.ScheduleHint(
            id=self.id,
            cron=self.cron,
            airflow_dag_id=self.dag_id,
            source=self.source,
            enabled=self.enabled,
            kind=self.kind,
            precludes=list(self.precludes),
            horizon_s=int(self.horizon_s),
            after=list(self.after),
            after_mode=self.after_mode,
            timezone=self.timezone,
            description=self.description,
            runner=self.runner,
        )
        for c in self.claims:
            h.claims.add(leaf=str(c.get("leaf") or ""), gpu=int(c.get("gpu") or 0))
        for k, v in self.postures.items():
            h.postures[str(k)] = str(v)
        return h

    def to_record(self) -> scheduler_pb2.WorkloadRecord:
        return scheduler_pb2.WorkloadRecord(
            workload=self.to_hint(),
            peer=self.peer,
            dag_id=self.dag_id,
            synced_ns=int(self.synced_ns),
            state=self.state,
            error=self.error,
        )

    def registry_row(self) -> dict[str, Any]:
        """What the dynamic DAG module reads (no state/error — errored entries are not published)."""
        return {
            "peer": self.peer,
            "id": self.id,
            "kind": self.kind,
            "dag_id": self.dag_id,
            "cron": self.cron,
            "timezone": self.timezone,
            "after": list(self.after),
            "after_kinds": list(self.after_kinds),
            "after_mode": self.after_mode,
            "claims": [dict(c) for c in self.claims],
            "precludes": list(self.precludes),
            "postures": dict(self.postures),
            "horizon_s": int(self.horizon_s),
            "runner": self.runner,
            "source": self.source,
            "enabled": bool(self.enabled),
            "description": self.description,
            "engine_build": self.engine_build,
        }


def default_dag_id(peer: str, kind: str) -> str:
    safe = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in f"{peer}_{kind}")
    return safe


class WorkloadCatalog:
    """Per-peer catalogue files + the federation registry Variable in Airflow."""

    def __init__(
        self,
        root: Path,
        airflow: AirflowClient | Callable[[], AirflowClient] | None,
        *,
        leaf_max: Callable[[str], int | None] | None = None,
        allowed_peers: frozenset[str] = ALLOWED_PEERS,
        clock_ns: Callable[[], int] = _now_ns,
        variable_key: str = VARIABLE_KEY,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._airflow = airflow
        self._leaf_max = leaf_max
        self.allowed_peers = allowed_peers
        self._clock = clock_ns
        self.variable_key = variable_key
        self._mu = threading.RLock()

    # ── airflow handle (lazy: the engine boots with Airflow down) ────────────
    def airflow(self) -> AirflowClient:
        if self._airflow is None:
            raise CatalogError(GURU_CATALOG_AIRFLOW, "no Airflow client configured for the catalogue")
        if callable(self._airflow) and not hasattr(self._airflow, "get_variable"):
            self._airflow = self._airflow()  # factory → client, once
        return self._airflow  # type: ignore[return-value]

    # ── peer files ───────────────────────────────────────────────────────────
    def _peer_path(self, peer: str) -> Path:
        safe = "".join(ch for ch in peer if ch.isalnum() or ch in "-_")
        if not safe or safe != peer:
            raise CatalogError(GURU_CATALOG, f"peer {peer!r} is not a plain name")
        return self.root / f"{safe}.json"

    def load(self, peer: str) -> list[CatalogEntry]:
        p = self._peer_path(peer)
        try:
            doc = json.loads(p.read_text())
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as e:
            raise CatalogError(GURU_CATALOG, f"catalogue file {p} unreadable: {e!r}; Fix: inspect/remove it") from e
        return [CatalogEntry.from_json(x) for x in (doc.get("entries") or []) if isinstance(x, dict)]

    def load_all(self) -> list[CatalogEntry]:
        out: list[CatalogEntry] = []
        for p in sorted(self.root.glob("*.json")):
            if p.name == "registry.json":
                continue
            out.extend(self.load(p.stem))
        return out

    def _write_peer(self, peer: str, entries: list[CatalogEntry]) -> None:
        p = self._peer_path(peer)
        tmp = p.with_suffix(".json.tmp")
        body = {"peer": peer, "synced_ns": self._clock(), "entries": [e.to_json() for e in entries]}
        try:
            tmp.write_text(json.dumps(body, sort_keys=True, indent=1))
            os.replace(tmp, p)
        except OSError as e:
            raise CatalogError(GURU_CATALOG, f"catalogue file {p} unwritable: {e!r}; Fix: check {self.root}") from e

    # ── validation ───────────────────────────────────────────────────────────
    def _validate(self, entry: CatalogEntry, known_ids: dict[str, CatalogEntry]) -> None:
        """Set state/error in place. `known_ids` = every id in the federation after this sync."""
        problems: list[str] = []
        if not entry.id:
            problems.append("id is required")
        if not entry.kind:
            problems.append("kind is required")
        if entry.source == SOURCE_ENGINE:
            entry.dag_id = ""
        else:
            if not entry.dag_id:
                entry.dag_id = default_dag_id(entry.peer, entry.kind or entry.id)
        seen_leaves: dict[str, int] = {}
        for c in entry.claims:
            leaf = str(c.get("leaf") or "").strip()
            gpu = int(c.get("gpu") or 0)
            if not leaf:
                problems.append("claim without a leaf")
                continue
            if gpu < 0:
                problems.append(f"claim {leaf}: negative gpu")
            seen_leaves[leaf] = seen_leaves.get(leaf, 0) + gpu
        if self._leaf_max is not None:
            for leaf, gpu in seen_leaves.items():
                mx = self._leaf_max(leaf)
                if mx is None:
                    problems.append(f"claim on unknown YK leaf {leaf!r}")
                elif gpu > mx:
                    problems.append(f"claim {gpu} GPU on {leaf} exceeds the leaf max {mx}")
        entry.after_kinds = []
        for a in entry.after:
            ref = known_ids.get(a)
            if ref is None:
                problems.append(f"after {a!r}: no such catalogue id in the federation")
                continue
            if ref.source == SOURCE_ENGINE and not ref.kind:
                problems.append(f"after {a!r}: referenced entry has no kind")
                continue
            entry.after_kinds.append(ref.kind)
        if entry.after_mode and entry.after_mode not in AFTER_MODES:
            problems.append(f"after_mode {entry.after_mode!r}: expected one of {sorted(AFTER_MODES)}")
        if entry.after_mode and not entry.after:
            problems.append("after_mode set without after — name the workloads it follows")
        if entry.cron and entry.after and not entry.after_mode:
            # Airflow allows time OR assets (AssetOrTimeSchedule) but the catalogue
            # keeps it explicit: an entry that wants both says how `after` is read.
            problems.append(
                "both cron and after set — choose time-scheduled or asset-scheduled, "
                "or set after_mode (all|any) for a time-OR-assets schedule"
            )
        if problems:
            entry.state = STATE_ERROR
            entry.error = "; ".join(problems)
            return
        entry.error = ""
        if entry.source == SOURCE_ENGINE:
            entry.state = STATE_ENGINE_DECLARED
        elif entry.enabled:
            entry.state = STATE_MATERIALIZED
        else:
            entry.state = STATE_PAUSED

    # ── sync ─────────────────────────────────────────────────────────────────
    def sync(
        self,
        peer: str,
        hints: list[engine_pb2.ScheduleHint],
        *,
        replace: bool,
        engine_build: str = "",
    ) -> list[CatalogEntry]:
        peer = (peer or "").strip().lower()
        if peer not in self.allowed_peers:
            raise CatalogError(GURU_CATALOG, f"unknown peer {peer!r}; allowed: {sorted(self.allowed_peers)}")
        now = self._clock()
        with self._mu:
            previous = {e.id: e for e in self.load(peer)}
            incoming: list[CatalogEntry] = []
            ids_seen: set[str] = set()
            for h in hints:
                e = CatalogEntry.from_hint(peer, h, engine_build=engine_build, now_ns=now)
                if e.id in ids_seen:
                    e.state, e.error = STATE_ERROR, f"duplicate catalogue id {e.id!r} in one sync"
                ids_seen.add(e.id)
                incoming.append(e)
            merged: dict[str, CatalogEntry] = dict(previous) if not replace else {}
            if replace:
                # Whole-catalogue semantics: what the peer no longer submits is
                # kept for history but paused — Airflow pauses its DAG.
                for old_id, old in previous.items():
                    if old_id not in ids_seen:
                        old.enabled = False
                        old.state = STATE_PAUSED if old.state != STATE_ERROR else STATE_ERROR
                        old.synced_ns = now
                        merged[old_id] = old
            for e in incoming:
                merged[e.id] = e
            # Validate against the federation view AFTER this sync (other peers' files + ours).
            federation: dict[str, CatalogEntry] = {}
            for other in self.load_all():
                if other.peer != peer:
                    federation[other.id] = other
            federation.update(merged)
            for e in merged.values():
                if e.state == STATE_ERROR and e.error.startswith("duplicate"):
                    continue
                self._validate(e, federation)
            entries = sorted(merged.values(), key=lambda x: x.id)
            self._write_peer(peer, entries)
            log.info(
                "workload catalogue: peer=%s synced %d entr%s (replace=%s): %s",
                peer, len(entries), "y" if len(entries) == 1 else "ies", replace,
                ", ".join(f"{e.id}[{e.state}]" for e in entries) or "-",
            )
            self.publish()
            return entries

    def list(self, peer: str = "") -> list[CatalogEntry]:
        peer = (peer or "").strip().lower()
        with self._mu:
            entries = self.load(peer) if peer else self.load_all()
        return sorted(entries, key=lambda e: (e.peer, e.id))

    # ── registry (Airflow Variable) ──────────────────────────────────────────
    def registry(self) -> dict[str, Any]:
        rows = [
            e.registry_row()
            for e in sorted(self.load_all(), key=lambda e: (e.peer, e.id))
            if e.state != STATE_ERROR
        ]
        return {"workloads": rows}

    @staticmethod
    def _canonical(rows: list[dict[str, Any]]) -> str:
        return json.dumps(rows, sort_keys=True, separators=(",", ":"))

    def _registry_meta_path(self) -> Path:
        return self.root / "registry.json"

    def _read_meta(self) -> dict[str, Any]:
        try:
            return json.loads(self._registry_meta_path().read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _write_meta(self, meta: dict[str, Any]) -> None:
        p = self._registry_meta_path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, sort_keys=True, indent=1))
        os.replace(tmp, p)

    def publish(self, *, force: bool = False) -> bool:
        """Write the registry Variable when its content changed (or the remote lacks it).

        Also flips `is_paused` on already-registered DAGs whose `enabled` changed —
        `is_paused_upon_creation` only governs the first registration. A DAG the
        processor has not parsed yet is skipped (it will be born paused/unpaused
        from the registry). Returns True when the Variable was written.
        """
        with self._mu:
            rows = self.registry()["workloads"]
            canon = self._canonical(rows)
            digest = hashlib.sha256(canon.encode()).hexdigest()
            meta = self._read_meta()
            previous_rows = {(r["peer"], r["id"]): r for r in (meta.get("rows") or [])}
            unchanged = meta.get("sha256") == digest and meta.get("published") is True
            af = self.airflow()
            if unchanged and not force:
                # Cheap consistency: the remote must still carry this version.
                remote = af.get_variable(self.variable_key)
                if remote is not None:
                    try:
                        if json.loads(remote).get("sha256") == digest:
                            return False
                    except (ValueError, AttributeError):
                        pass
            version = int(meta.get("version") or 0) + (0 if unchanged else 1)
            doc = {
                "version": version,
                "sha256": digest,
                "synced_ns": self._clock(),
                "workloads": rows,
            }
            try:
                af.set_variable(self.variable_key, json.dumps(doc, sort_keys=True), description=VARIABLE_DESCRIPTION)
            except AirflowError:
                meta.update({"version": version, "sha256": digest, "published": False, "rows": rows})
                self._write_meta(meta)
                raise
            self._write_meta({"version": version, "sha256": digest, "published": True, "rows": rows, "published_ns": self._clock()})
            log.info("workload catalogue: registry v%d published to Airflow Variable %s (%d workloads)", version, self.variable_key, len(rows))
            # Pause/unpause flips for DAGs that already exist.
            for r in rows:
                if not r.get("dag_id"):
                    continue
                prev = previous_rows.get((r["peer"], r["id"]))
                if prev is not None and bool(prev.get("enabled")) == bool(r.get("enabled")):
                    continue
                if prev is None and r.get("enabled"):
                    continue  # new + enabled: born unpaused
                try:
                    af.set_paused(r["dag_id"], not bool(r.get("enabled")))
                    log.info("workload catalogue: %s is_paused=%s", r["dag_id"], not bool(r.get("enabled")))
                except AirflowError as e:
                    if e.guru in (GURU_DAGMISSING, GURU_API) and ("404" in e.what or "not registered" in e.what):
                        log.info("workload catalogue: %s not registered yet — born from the registry", r["dag_id"])
                        continue
                    raise
            return True

    def resume(self) -> bool:
        """Boot: republish a registry the previous process could not (Airflow was down)."""
        meta = self._read_meta()
        if meta.get("published") is True or not self.load_all():
            return False
        try:
            return self.publish(force=True)
        except (AirflowError, CatalogError) as e:
            log.warning("workload catalogue resume: publish deferred: %s", e)
            return False
