"""Data-product history: seed catalog + Iceberg warehouse + agent brief.

Sole SoR is Iceberg on RustFS (``details`` fact log, ``tx`` header, ``hx_*``).
pglite (Postgres :5455) is administrative — this module must never write
product or hx rows there.

JSON catalog is a bootstrap seed for a first assert into ``details``.
It is not a warehouse.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from signals.ops.procedures import DATA_PRODUCT_HISTORY_REVIEW, get_method
from signals.ops.warehouse import DataProductWarehouse, default_warehouse
from signals.uuidv7 import mint as mint_uuidv7

CATALOG = Path("config/platform/data-products.json")
BRIEF_DIR = Path("build/state/data-product-briefs")

EVENT_TYPE = "dev.signals.dataproduct.updated"


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    p = path or CATALOG
    return json.loads(p.read_text(encoding="utf-8"))


def products(path: Path | None = None) -> list[dict[str, Any]]:
    return list(load_catalog(path).get("products") or [])


def product_by_id(product_id: str, path: Path | None = None) -> dict[str, Any] | None:
    for row in products(path):
        if row.get("id") == product_id:
            return row
    return None


def resolve_product(
    product_id: str,
    *,
    catalog: Path | None = None,
    warehouse: DataProductWarehouse | None = None,
) -> dict[str, Any] | None:
    """Prefer warehouse (SoR); fall back to seed JSON for first INSERT."""
    if warehouse is not None:
        row = warehouse.get_product(product_id)
        if row is not None:
            return row
    return product_by_id(product_id, catalog)


def record_event(
    product_id: str,
    *,
    kind: str = "updated",
    summary: str = "",
    source: str = "signals-protocol",
    agent: str = "pending",
    warehouse: DataProductWarehouse | None = None,
    product: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a tx and assert current details. Never writes pglite or JSONL."""
    wh = warehouse if warehouse is not None else default_warehouse()
    tid = mint_uuidv7()
    ev = {
        "tx_id": tid,
        "event_id": tid,
        "ts": time.time(),
        "ts_ns": time.time_ns(),
        "type": EVENT_TYPE,
        "ce_type": EVENT_TYPE,
        "product_id": product_id,
        "kind": kind,
        "summary": summary,
        "source": source,
        "agent": agent,
    }
    wh.insert_tx(ev)
    if product is not None:
        wh.assert_details(product, tid)
    return ev


def load_events(
    *,
    limit: int = 50,
    warehouse: DataProductWarehouse | None = None,
) -> list[dict[str, Any]]:
    wh = warehouse if warehouse is not None else default_warehouse()
    return wh.list_tx(limit=limit)


def walk_history_review(verdict: str) -> dict[str, Any]:
    """Conclude data-product.history-review from the observer verdict.

    Nominal (including in-progress on the legal path, or not-upkeep) →
    understood. Off-nominal → failed. Holding ``reviewing`` is only for a
    spawn that has not yet observed.
    """
    fsm = get_method(DATA_PRODUCT_HISTORY_REVIEW)
    fsm.step("event_received")
    fsm.step("reviewing")
    fsm.step("failed" if verdict == "off_nominal" else "understood")
    return fsm.as_method()


def agent_brief(product: dict[str, Any], event: dict[str, Any]) -> str:
    """What an ACP agent (Grok-Subscription or Grok-Local/Qwen3.8) must cover."""
    pid = product.get("id") or product.get("product_id") or "?"
    body = (
        f"# Data product review: {pid}\n\n"
        f"Peer: {product.get('peer')}\n"
        f"Kind: {product.get('kind')}\n"
        f"Title: {product.get('title')}\n"
        f"YK leaf: {product.get('leaf')}\n"
        f"Event: {event.get('kind')} ({event.get('type')})\n"
        f"tx: {event.get('tx_id') or event.get('event_id')}\n"
        f"Summary: {event.get('summary') or '(none)'}\n\n"
        "Understand **at minimum**:\n"
        "1. **Quality** — is this product still fit for downstream agents?\n"
        "2. **Lineage** — what runs/tables/models produced this update (Atlas OL)?\n"
        "3. **Delta** — what changed vs the prior tx for this product?\n\n"
        f"Agent focus: {product.get('agent_focus')}\n"
        "Capabilities: grok-subscription [thinking] or grok-local Qwen3.8 [thinking,vision].\n"
        "Queue for subscription work: root.external.subscription.rate-limited.\n"
        "Persist traces on Iceberg hx_* keyed to tx_id (RustFS). Do not copy into Postgres AGE.\n"
    )
    if pid == "signals.metaflow.snapshots" or product.get("kind") == "snapshot":
        from signals.ops.metaflow_store import snapshot_understanding

        body += snapshot_understanding(product, event)
    return body


def seed_details(
    warehouse: DataProductWarehouse | None = None,
    catalog: Path | None = None,
) -> list[str]:
    """First tx + details asserts from the JSON seed. Skips products already in SoR."""
    wh = warehouse if warehouse is not None else default_warehouse()
    written: list[str] = []
    for prod in products(catalog):
        pid = prod.get("id")
        if not pid:
            continue
        if wh.get_product(pid) is None:
            record_event(
                pid,
                kind="created",
                summary="seed",
                warehouse=wh,
                product=prod,
            )
            written.append(pid)
    return written


def review(
    product_id: str,
    *,
    kind: str = "updated",
    summary: str = "",
    catalog: Path | None = None,
    warehouse: DataProductWarehouse | None = None,
    product: dict[str, Any] | None = None,
    source: str = "signals-protocol",
) -> tuple[dict[str, Any], Path]:
    """Record a tx, assert details, write the agent brief. Does not spawn ACP."""
    wh = warehouse if warehouse is not None else default_warehouse()
    prod = product if product is not None else resolve_product(
        product_id, catalog=catalog, warehouse=wh
    )
    if prod is None:
        raise KeyError(f"unknown data product {product_id!r}")
    ev = record_event(
        product_id,
        kind=kind,
        summary=summary,
        source=source,
        warehouse=wh,
        product=prod,
    )
    brief = agent_brief(prod, ev)
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(ev.get("ts") or time.time())
    out = BRIEF_DIR / f"{stamp}-{product_id.replace('.', '_')}.md"
    out.write_text(brief, encoding="utf-8")
    ev["brief_path"] = str(out)
    hx_agent = str(prod.get("assessment_agent") or "briefed")
    ev["agent"] = hx_agent
    wh.insert_hx_reasoning(
        {
            "tx_id": ev["tx_id"],
            "event_id": ev["tx_id"],
            "product_id": product_id,
            "ts_ns": ev["ts_ns"],
            "agent": hx_agent,
            "quality": str(prod.get("quality") or ""),
            "lineage": str(prod.get("lineage") or ""),
            "delta": str(prod.get("delta") or ""),
            "trace": brief,
        }
    )
    if prod.get("assessment"):
        wh.insert_hx_exchange(
            {
                "tx_id": ev["tx_id"],
                "event_id": ev["tx_id"],
                "product_id": product_id,
                "ts_ns": ev["ts_ns"],
                "agent": hx_agent,
                "role": "observer",
                "message": (
                    f"assessment={prod.get('assessment')} "
                    f"upkeep_nominal={prod.get('upkeep_nominal')} "
                    f"fsm={prod.get('upkeep_fsm') or 'n/a'}"
                ),
            }
        )
        ev["review"] = walk_history_review(str(prod.get("assessment")))
        ev["assessment"] = prod.get("assessment")
    return ev, out
