"""Data-product warehouse — details / tx / hx over Kudu tier0 + Iceberg tier1.

Writers land on ``*_tier0`` (Kudu). Readers use Impala views that UNION ALL
tiers. Expire hot data with DROP RANGE PARTITION, never row DELETE.
pglite is administrative only — this module refuses any Postgres DSN.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from signals.uuidv7 import NonUuid7TxId, epoch_hour_of, is_uuidv7, mint as mint_uuidv7

# Repo root, not cwd: apply_schema must work from any working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
# tier1 tables are NOT SQL: Impala Iceberg DDL writes metadata the
# MultiMetaProvider cannot load back (2026-08-30 phantom-table incident).
# They are created through Polaris by signals.ops.iceberg_register, between
# the kudu and views files — see signals.ops.__main__ schema-apply.
SCHEMA_SQL = (
    _REPO_ROOT / "config/platform/data-products-kudu.sql",
    _REPO_ROOT / "config/platform/data-products-views.sql",
)
DATABASE = "signals_dataproducts"
TABLES = ("tx", "details", "hx_exchange", "hx_reasoning")
TIER0 = {
    "tx": "tx_tier0",
    "details": "details_tier0",
    "hx_exchange": "hx_exchange_tier0",
    "hx_reasoning": "hx_reasoning_tier0",
}
DETAIL_ATTRS = ("peer", "title", "kind", "leaf", "agent_focus")
DETAIL_SKIP = frozenset(
    {"id", "product_id", "e", "tx_id", "event_id", "ts_ns", "updated_ns", "epoch_hour"}
)


def detail_keys(product: dict[str, Any]) -> list[str]:
    """Catalog attrs plus extra scalar facts (Metaflow snapshot fields, …)."""
    keys: list[str] = list(DETAIL_ATTRS)
    for k, v in product.items():
        if k in DETAIL_SKIP or k in keys:
            continue
        if v is None or isinstance(v, (dict, list)):
            continue
        if str(k).startswith("_"):
            continue
        keys.append(str(k))
    return keys


NS_PER_HOUR = 3_600_000_000_000
HOURS_PER_WEEK = 168
SETTLE_WEEKS = 4


def epoch_hour(ts_ns: int | None = None) -> int:
    """UTC hours since 1970-01-01. Kudu range *unit* (week-wide tablets)."""
    ns = int(ts_ns if ts_ns is not None else time.time_ns())
    return ns // NS_PER_HOUR


def week_start_hour(hour: int) -> int:
    return (int(hour) // HOURS_PER_WEEK) * HOURS_PER_WEEK


def settle_before_hour(now_hour: int | None = None) -> int:
    """Exclusive upper bound: weeks with end <= now - 4 weeks are settleable."""
    h = int(now_hour if now_hour is not None else epoch_hour())
    return week_start_hour(h) - SETTLE_WEEKS * HOURS_PER_WEEK

_PG_MARKERS = (
    "postgresql://",
    "postgres://",
    "jdbc:postgresql",
)


class WarehouseError(RuntimeError):
    """Product-path warehouse failure (fail-closed)."""


def refuse_postgres(target: str) -> None:
    """Raise if *target* looks like a pglite / Postgres product store."""
    low = target.lower()
    for mark in _PG_MARKERS:
        if mark in low:
            raise WarehouseError(
                f"refusing pglite/Postgres product store {target!r} — "
                "sole SoR is Iceberg on RustFS (details / tx / hx)"
            )


class DataProductWarehouse(Protocol):
    """Product inventory as details+tx+hx. Never a Postgres heap."""

    def insert_tx(self, event: dict[str, Any]) -> None: ...

    def assert_details(self, product: dict[str, Any], tx_id: str) -> None: ...

    def insert_hx_exchange(self, row: dict[str, Any]) -> None: ...

    def insert_hx_reasoning(self, row: dict[str, Any]) -> None: ...

    def get_product(self, product_id: str) -> dict[str, Any] | None: ...

    def list_details(self) -> list[dict[str, Any]]: ...

    def list_tx(self, *, limit: int = 50) -> list[dict[str, Any]]: ...


def _product_id(product: dict[str, Any]) -> str:
    return str(product.get("id") or product.get("product_id") or product.get("e") or "")


def _tx_id(event: dict[str, Any]) -> str:
    return str(event.get("tx_id") or event.get("event_id") or "")


def _require_uuidv7(tx_id: str, *, product_id: str = "", source: str = "") -> None:
    if not is_uuidv7(tx_id):
        raise NonUuid7TxId(tx_id, product_id=product_id, source=source)


def project_details(facts: list[dict[str, Any]], product_id: str) -> dict[str, Any] | None:
    """Current inventory: latest fact per attribute (retract tombstones)."""
    latest: dict[str, tuple[str, bool, str]] = {}
    for row in facts:
        if row.get("e") != product_id:
            continue
        a = str(row.get("a") or "")
        t = str(row.get("t") or "")
        if not a:
            continue
        prev = latest.get(a)
        if prev is None or t >= prev[0]:
            latest[a] = (t, bool(row.get("op", True)), str(row.get("v") or ""))
    live = {a: (t, v) for a, (t, op, v) in latest.items() if op}
    if not live:
        return None
    out: dict[str, Any] = {"product_id": product_id, "id": product_id}
    max_t = ""
    for a, (t, v) in live.items():
        out[a] = v
        if t >= max_t:
            max_t = t
    out["tx_id"] = max_t
    return out


@dataclass
class MemoryWarehouse:
    """Hermetic stand-in for tests. Same shape as Iceberg; not a second SoR."""

    details: list[dict[str, Any]] = field(default_factory=list)
    tx: list[dict[str, Any]] = field(default_factory=list)
    hx_exchange: list[dict[str, Any]] = field(default_factory=list)
    hx_reasoning: list[dict[str, Any]] = field(default_factory=list)

    def insert_tx(self, event: dict[str, Any]) -> None:
        ev = dict(event)
        tid = ev.get("tx_id") or ev.get("event_id") or mint_uuidv7()
        _require_uuidv7(str(tid), product_id=str(ev.get("product_id") or ""), source=str(ev.get("source") or ""))
        ev["tx_id"] = tid
        ev.setdefault("event_id", tid)
        ev.setdefault("ts_ns", int(time.time_ns()))
        self.tx.append(ev)

    def assert_details(self, product: dict[str, Any], tx_id: str) -> None:
        pid = _product_id(product)
        if not pid:
            raise WarehouseError("details fact needs product id")
        for a in detail_keys(product):
            self.details.append(
                {
                    "e": pid,
                    "a": a,
                    "v": str(product.get(a) or ""),
                    "t": tx_id,
                    "op": True,
                }
            )

    def insert_hx_exchange(self, row: dict[str, Any]) -> None:
        rec = dict(row)
        rec.setdefault("tx_id", rec.get("event_id"))
        self.hx_exchange.append(rec)

    def insert_hx_reasoning(self, row: dict[str, Any]) -> None:
        rec = dict(row)
        rec.setdefault("tx_id", rec.get("event_id"))
        self.hx_reasoning.append(rec)

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        return project_details(self.details, product_id)

    def list_details(self) -> list[dict[str, Any]]:
        ids = {str(r.get("e")) for r in self.details if r.get("e")}
        return [p for pid in sorted(ids) if (p := project_details(self.details, pid))]

    def list_tx(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.tx[-limit:]


class ImpalaWarehouse:
    """Live Iceberg via Impala HS2. Kerberos FQDN only — never loopback PG."""

    def __init__(self, connect=None) -> None:
        self._connect = connect
        self._conn = None

    def _conn_open(self):
        if self._conn is not None:
            return self._conn
        from signals.impala import impala_connect

        fn = self._connect or impala_connect
        self._conn = fn()
        return self._conn

    def _execute(self, sql: str, fetch: bool = False):
        refuse_postgres(sql)
        cur = self._conn_open().cursor()
        cur.execute(sql)
        if fetch:
            return cur.fetchall()
        return None

    def apply_schema(self, sql_path: Path | None = None) -> None:
        """Apply every statement in every schema file; fail with ALL errors.

        A single bad statement (e.g. a reserved word) must not silently leave
        the inventory half-built — every remaining statement still runs, then
        one aggregate WarehouseError reports each failure.
        """
        paths: tuple[Path, ...]
        if sql_path is None:
            paths = SCHEMA_SQL
        else:
            paths = (sql_path,)
        failures: list[str] = []
        for path in paths:
            raw = path.read_text(encoding="utf-8")
            stmt: list[str] = []
            for line in raw.splitlines():
                if line.strip().startswith("--"):
                    continue
                stmt.append(line)
            blob = "\n".join(stmt)
            for part in blob.split(";"):
                sql = part.strip()
                if not sql:
                    continue
                try:
                    self._execute(sql)
                except Exception as e:  # noqa: BLE001 — collected and re-raised
                    head = " ".join(sql.split())[:80]
                    failures.append(f"{path.name}: {head!r}: {e}")
        if failures:
            raise WarehouseError(
                f"apply_schema: {len(failures)} statement(s) failed:\n  "
                + "\n  ".join(failures)
            )

    def insert_tx(self, event: dict[str, Any]) -> None:
        ts = int(event.get("ts_ns") or time.time_ns())
        raw_tid = _tx_id(event) or mint_uuidv7()
        pid_raw = str(event.get("product_id") or "")
        _require_uuidv7(raw_tid, product_id=pid_raw, source=str(event.get("source") or ""))
        hour = int(event.get("epoch_hour") or epoch_hour_of(raw_tid) or epoch_hour(ts))
        tid = _sql_str(raw_tid)
        pid = _sql_str(pid_raw)
        kind = _sql_str(event.get("kind") or "updated")
        summary = _sql_str(event.get("summary"))
        source = _sql_str(event.get("source") or "signals-protocol")
        ce = _sql_str(event.get("type") or event.get("ce_type") or "")
        self._execute(
            f"INSERT INTO {DATABASE}.{TIER0['tx']} "
            f"(epoch_hour, product_id, tx_id, ts_ns, kind, summary, source, ce_type) "
            f"VALUES ({hour}, {pid}, {tid}, {ts}, {kind}, {summary}, {source}, {ce})"
        )

    def assert_details(self, product: dict[str, Any], tx_id: str) -> None:
        pid = _product_id(product)
        if not pid:
            raise WarehouseError("details fact needs product id")
        _require_uuidv7(tx_id, product_id=pid)
        ts = int(product.get("ts_ns") or product.get("updated_ns") or time.time_ns())
        hour = int(product.get("epoch_hour") or epoch_hour_of(tx_id) or epoch_hour(ts))
        e = _sql_str(pid)
        t = _sql_str(tx_id)
        for a in detail_keys(product):
            self._execute(
                f"INSERT INTO {DATABASE}.{TIER0['details']} "
                f"(epoch_hour, e, a, t, v, op, ts_ns) "
                f"VALUES ({hour}, {e}, {_sql_str(a)}, {t}, {_sql_str(product.get(a))}, true, {ts})"
            )

    def insert_hx_exchange(self, row: dict[str, Any]) -> None:
        ts = int(row.get("ts_ns") or time.time_ns())
        hour = int(row.get("epoch_hour") or epoch_hour(ts))
        tid = _sql_str(row.get("tx_id") or row.get("event_id"))
        self._execute(
            f"INSERT INTO {DATABASE}.{TIER0['hx_exchange']} "
            f"(epoch_hour, product_id, tx_id, ts_ns, agent, actor, message) VALUES ("
            f"{hour}, {_sql_str(row.get('product_id'))}, {tid}, {ts}, "
            f"{_sql_str(row.get('agent'))}, {_sql_str(row.get('actor'))}, "
            f"{_sql_str(row.get('message'))})"
        )

    def insert_hx_reasoning(self, row: dict[str, Any]) -> None:
        ts = int(row.get("ts_ns") or time.time_ns())
        hour = int(row.get("epoch_hour") or epoch_hour(ts))
        tid = _sql_str(row.get("tx_id") or row.get("event_id"))
        self._execute(
            f"INSERT INTO {DATABASE}.{TIER0['hx_reasoning']} "
            f"(epoch_hour, product_id, tx_id, agent, ts_ns, quality, lineage, delta, trace) "
            f"VALUES ({hour}, {_sql_str(row.get('product_id'))}, {tid}, "
            f"{_sql_str(row.get('agent'))}, {ts}, {_sql_str(row.get('quality'))}, "
            f"{_sql_str(row.get('lineage'))}, {_sql_str(row.get('delta'))}, "
            f"{_sql_str(row.get('trace'))})"
        )

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        rows = self._execute(
            f"SELECT e, a, v, t, op FROM {DATABASE}.details "
            f"WHERE e = {_sql_str(product_id)}",
            fetch=True,
        )
        facts = [
            {"e": r[0], "a": r[1], "v": r[2], "t": r[3], "op": bool(r[4])}
            for r in (rows or [])
        ]
        return project_details(facts, product_id)

    def list_details(self) -> list[dict[str, Any]]:
        rows = self._execute(
            f"SELECT e, a, v, t, op FROM {DATABASE}.details",
            fetch=True,
        )
        facts = [
            {"e": r[0], "a": r[1], "v": r[2], "t": r[3], "op": bool(r[4])}
            for r in (rows or [])
        ]
        ids = {str(r["e"]) for r in facts if r.get("e")}
        return [p for pid in sorted(ids) if (p := project_details(facts, pid))]

    def list_tx(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._execute(
            f"SELECT tx_id, product_id, ts_ns, kind, summary, source, ce_type "
            f"FROM {DATABASE}.tx ORDER BY ts_ns DESC LIMIT {int(limit)}",
            fetch=True,
        )
        out = []
        for r in rows or []:
            out.append(
                {
                    "tx_id": r[0],
                    "event_id": r[0],
                    "product_id": r[1],
                    "ts_ns": r[2],
                    "kind": r[3],
                    "summary": r[4],
                    "source": r[5],
                    "ce_type": r[6],
                }
            )
        return list(reversed(out))


def _sql_str(value: Any) -> str:
    s = "" if value is None else str(value)
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def default_warehouse() -> DataProductWarehouse:
    """Product path is Impala Iceberg. Tests inject MemoryWarehouse."""
    backend = os.environ.get("SIGNALS_WAREHOUSE", "impala").strip().lower()
    if backend in {"memory", "test"}:
        return MemoryWarehouse()
    if backend in {"postgres", "pglite", "pg"}:
        raise WarehouseError("SIGNALS_WAREHOUSE cannot be pglite/postgres")
    return ImpalaWarehouse()
