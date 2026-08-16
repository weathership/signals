"""Metaflow snapshot product — datastore must be RustFS, never local disk.

First Signals Data Product (``signals.metaflow.snapshots``). Each Metaflow
run is an immutable (code, data, deps) triple. Those objects live on RustFS;
this module maps one run onto ``details`` facts + a ``tx`` so ACP can
understand *what was retained*, not merely that a run finished.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from signals.ops.procedures import DATA_PRODUCT_HISTORY_REVIEW, DATA_PRODUCT_TIER_UPKEEP
from signals.ops.tier_upkeep import YK_APP_ID, YK_QUEUE
from signals.ops.warehouse import HOURS_PER_WEEK, WarehouseError

PRODUCT_ID = "signals.metaflow.snapshots"
PROFILE = Path("config/metaflow/platform.json")
RUSTFS_PORT = "9010"
ALLOWED_ROOT_PREFIXES = ("s3://metaflow/", "s3://signals-dataproducts/")
UPKEEP_FLOWS = frozenset({"DataProductTierUpkeep"})
ASSESSMENT_AGENT = "acp-observer"

CATALOG_DEFAULTS: dict[str, str] = {
    "peer": "signals",
    "title": "Metaflow run snapshots",
    "kind": "snapshot",
    "leaf": "root.platform",
    "agent_focus": (
        "Observe data-product.tier-upkeep and confirm it is proceeding nominally "
        "(legal FSM, ADD next week, settle ≥ 4 weeks, snapshot on RustFS). "
        "Quality / lineage / delta are that observation — do not re-inventory."
    ),
}


def load_profile(path: Path | None = None) -> dict[str, Any]:
    p = path or PROFILE
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def require_rustfs(
    env: dict[str, str] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Fail closed if Metaflow would write a local (non-RustFS) snapshot."""
    env = dict(os.environ if env is None else env)
    prof = profile if profile is not None else load_profile()
    ds = (
        env.get("METAFLOW_DEFAULT_DATASTORE")
        or str(prof.get("METAFLOW_DEFAULT_DATASTORE") or "")
    ).strip().lower()
    if ds in {"", "local"}:
        raise WarehouseError(
            "Metaflow datastore is local or unset — snapshots MUST land on RustFS (s3)"
        )
    if ds != "s3":
        raise WarehouseError(f"Metaflow datastore {ds!r} is not s3/RustFS")
    root = (
        env.get("METAFLOW_DATASTORE_SYSROOT_S3")
        or str(prof.get("METAFLOW_DATASTORE_SYSROOT_S3") or "")
    ).strip()
    if not any(root.startswith(p) for p in ALLOWED_ROOT_PREFIXES):
        raise WarehouseError(
            f"METAFLOW_DATASTORE_SYSROOT_S3 {root!r} is not a Signals RustFS bucket"
        )
    endpoint = (
        env.get("METAFLOW_S3_ENDPOINT_URL")
        or env.get("AWS_ENDPOINT_URL_S3")
        or str(prof.get("METAFLOW_S3_ENDPOINT_URL") or "")
    )
    if RUSTFS_PORT not in endpoint and "rustfs" not in endpoint.lower():
        raise WarehouseError(
            f"S3 endpoint {endpoint!r} is not RustFS (:{RUSTFS_PORT})"
        )
    return {
        "datastore": "s3",
        "datastore_root": root,
        "rustfs_endpoint": endpoint,
        "object_store": "rustfs",
    }


def run_attr(flow: str, run_id: str, name: str) -> str:
    """Per-run fact key so latest-wins still keeps every snapshot on the product."""
    return f"run.{flow}/{run_id}.{name}"


def retained_snapshots(product: dict[str, Any]) -> list[dict[str, str]]:
    """Project run-qualified snapshot_uri facts into a list of retained runs."""
    suffix = ".snapshot_uri"
    prefix = "run."
    out: list[dict[str, str]] = []
    for k, v in product.items():
        if not (k.startswith(prefix) and k.endswith(suffix) and v):
            continue
        pathspec = k[len(prefix) : -len(suffix)]
        flow, _, run_id = pathspec.partition("/")
        rec = {
            "pathspec": pathspec,
            "flow_name": flow,
            "run_id": run_id,
            "snapshot_uri": str(v),
        }
        for facet in ("code_package", "code_package_sha", "data_uri", "deps"):
            rec[facet] = str(product.get(run_attr(flow, run_id, facet)) or "")
        out.append(rec)
    out.sort(key=lambda r: r["pathspec"])
    return out


def expects_upkeep(run: dict[str, Any]) -> bool:
    """True when this run is (or claims to be) a tier-upkeep execution."""
    if run.get("upkeep") is not None:
        return True
    flow = str(run.get("flow_name") or "")
    app = str(run.get("yk_app_id") or "")
    return flow in UPKEEP_FLOWS or app == YK_APP_ID


def assess_upkeep(
    doc: dict[str, Any] | None,
    product: dict[str, Any],
    *,
    expected: bool,
) -> dict[str, str]:
    """ACP observer: is data-product.tier-upkeep proceeding nominally?

    Holding on the legal path is nominal (in progress). ``failed``, missing
    walk evidence, DELETE FROM, or a non-RustFS snapshot is off-nominal.
    Non-upkeep runs return ``not_upkeep`` (still an observation).
    """
    ok: list[str] = []
    off: list[str] = []

    if not expected and not doc:
        return {
            "assessment": "not_upkeep",
            "assessment_phase": "n/a",
            "upkeep_nominal": "n/a",
            "upkeep_fsm": "",
            "upkeep_method": "",
            "assessment_ok": "not an upkeep run",
            "assessment_off": "",
            "quality": f"snapshot on {product.get('object_store') or 'unknown'} "
            f"{product.get('snapshot_uri') or '(no uri)'}",
            "lineage": product.get("pathspec") or "",
            "delta": f"run {product.get('run_id') or '?'}",
        }

    if not doc:
        off.append("upkeep walk missing — cannot observe the method")
        return _assessment_pack(
            "off_nominal", "unobserved", "", ok, off, product, doc
        )

    fsm = doc.get("fsm") if isinstance(doc.get("fsm"), dict) else {}
    current = str(fsm.get("current") or "")
    method = str(doc.get("method") or fsm.get("name") or "")
    if method == DATA_PRODUCT_TIER_UPKEEP:
        ok.append("method is data-product.tier-upkeep")
    else:
        off.append(f"method {method!r} is not data-product.tier-upkeep")

    holding = set(fsm.get("holding") or ())
    if current == "failed":
        off.append("upkeep FSM is failed")
        phase = "failed"
    elif current == "settled":
        ok.append("FSM settled (terminal, not holding)")
        phase = "settled"
    elif current in holding:
        ok.append(f"FSM holding at {current} — proceeding, not done")
        phase = "in_progress"
    elif not current:
        off.append("upkeep FSM current missing")
        phase = "unobserved"
    else:
        off.append(f"unexpected FSM state {current!r}")
        phase = current

    add = doc.get("add") if isinstance(doc.get("add"), dict) else {}
    try:
        add_w = int(add.get("hi", 0)) - int(add.get("lo", 0))
    except (TypeError, ValueError):
        add_w = 0
    if add and add_w == HOURS_PER_WEEK:
        ok.append(f"ADD range is {HOURS_PER_WEEK}h")
    elif add:
        off.append(f"ADD range width {add_w} is not {HOURS_PER_WEEK}h")
    else:
        off.append("ADD range missing")

    settle = doc.get("settle") if isinstance(doc.get("settle"), dict) else None
    drop_sql = [str(s) for s in (doc.get("drop_sql") or [])]
    if settle is None:
        if drop_sql:
            off.append("DROP SQL present with no settle range")
        elif current == "settled":
            ok.append("ADD-only week (no settle)")
    else:
        try:
            settle_w = int(settle.get("hi", 0)) - int(settle.get("lo", 0))
        except (TypeError, ValueError):
            settle_w = 0
        if settle_w == HOURS_PER_WEEK:
            ok.append(f"settle range is {HOURS_PER_WEEK}h")
        else:
            off.append(f"settle range width {settle_w} is not {HOURS_PER_WEEK}h")
        if current in {"dropping", "settled"}:
            if not drop_sql:
                off.append("settle planned but DROP SQL missing")
            elif any("DELETE FROM" in s for s in drop_sql):
                off.append("DROP plan uses DELETE FROM (anti-pattern)")
            elif any("DROP RANGE PARTITION" in s for s in drop_sql):
                ok.append("expire is DROP RANGE PARTITION")
            else:
                off.append("DROP SQL has no DROP RANGE PARTITION")

    if str(product.get("object_store") or "") == "rustfs":
        ok.append("snapshot on RustFS")
    else:
        off.append("snapshot not on RustFS")
    if not product.get("snapshot_uri"):
        off.append("snapshot_uri missing")
    q = str(product.get("yk_queue") or doc.get("yk_queue") or "")
    if q and q != YK_QUEUE:
        off.append(f"YK queue {q!r} is not {YK_QUEUE}")
    elif q == YK_QUEUE:
        ok.append(f"YK queue {YK_QUEUE}")

    if off:
        verdict = "off_nominal"
    else:
        verdict = "nominal"
    return _assessment_pack(verdict, phase, current, ok, off, product, doc)


def _assessment_pack(
    verdict: str,
    phase: str,
    current: str,
    ok: list[str],
    off: list[str],
    product: dict[str, Any],
    doc: dict[str, Any] | None,
) -> dict[str, str]:
    add = (doc or {}).get("add") or {}
    settle = (doc or {}).get("settle")
    add_s = f"{add.get('lo')}-{add.get('hi')}" if add else "—"
    settle_s = (
        f"{settle.get('lo')}-{settle.get('hi')}" if isinstance(settle, dict) else "none"
    )
    nominal = "true" if verdict == "nominal" else "false"
    quality = (
        f"upkeep {verdict} ({phase}); snapshot {product.get('object_store') or '?'} "
        f"{product.get('snapshot_uri') or '—'}; ADD {add_s}; settle {settle_s}"
    )
    lineage = (
        f"{product.get('pathspec') or '?'} method={DATA_PRODUCT_TIER_UPKEEP} "
        f"yk={product.get('yk_app_id') or YK_APP_ID}@{product.get('yk_queue') or YK_QUEUE}"
    )
    prior = product.get("origin_run_id") or ""
    delta = f"run {product.get('run_id') or '?'} vs prior {prior or 'none'}; ADD {add_s}"
    return {
        "assessment": verdict,
        "assessment_phase": phase,
        "assessment_agent": ASSESSMENT_AGENT,
        "assessment_method": DATA_PRODUCT_HISTORY_REVIEW,
        "upkeep_nominal": nominal,
        "upkeep_fsm": current,
        "upkeep_method": DATA_PRODUCT_TIER_UPKEEP,
        "upkeep_add": add_s,
        "upkeep_settle": settle_s,
        "assessment_ok": "; ".join(ok),
        "assessment_off": "; ".join(off),
        "quality": quality,
        "lineage": lineage,
        "delta": delta,
    }


def run_from_current(current: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lift Metaflow ``current`` (+ optional extras) into the run dict."""
    if current is None:
        raise WarehouseError("Metaflow current is unset — refuse empty snapshot")
    run = dict(extra or {})
    run.setdefault("flow_name", str(getattr(current, "flow_name", "") or ""))
    run.setdefault("run_id", str(getattr(current, "run_id", "") or ""))
    pathspec = getattr(current, "pathspec", None)
    if pathspec:
        run.setdefault("pathspec", str(pathspec))
    origin = getattr(current, "origin_run_id", None)
    if origin:
        run.setdefault("origin_run_id", str(origin))
    code = getattr(current, "code", None)
    if code is not None:
        path = getattr(code, "path", None) or getattr(code, "_path", None)
        sha = getattr(code, "sha", None) or getattr(code, "_sha", None)
        if path:
            run.setdefault("code_package", str(path))
        if sha:
            run.setdefault("code_package_sha", str(sha))
    return run


def facts_from_run(
    run: dict[str, Any],
    *,
    catalog_row: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map one Metaflow execution onto details facts (plus catalog identity).

    Product ``e`` stays ``signals.metaflow.snapshots``. This run's triple is
    asserted both as ``latest_*`` (current view) and as ``run.{flow}/{id}.*``
    so every retained snapshot remains in the projection.
    """
    store = require_rustfs(env=env, profile=profile)
    row = dict(CATALOG_DEFAULTS)
    row.update(catalog_row or {})
    row["id"] = PRODUCT_ID
    row.update(store)

    flow = str(run.get("flow_name") or "")
    run_id = str(run.get("run_id") or "")
    if not flow or not run_id:
        raise WarehouseError("Metaflow run needs flow_name and run_id")

    root = store["datastore_root"].rstrip("/")
    code = str(run.get("code_package") or run.get("code_package_url") or "")
    sha = str(run.get("code_package_sha") or "")
    deps = str(run.get("deps") or run.get("environment") or "")
    snap = str(run.get("snapshot_uri") or "")
    if not snap:
        snap = f"{root}/{flow}/{run_id}"
    data_uri = str(run.get("data_uri") or f"{root}/{flow}/data")
    pathspec = str(run.get("pathspec") or f"{flow}/{run_id}")
    successful = run.get("successful")
    if isinstance(successful, bool):
        successful = "true" if successful else "false"
    elif successful is None:
        successful = "true"
    else:
        successful = str(successful)

    row["flow_name"] = flow
    row["run_id"] = run_id
    row["pathspec"] = pathspec
    row["code_package"] = code
    row["code_package_sha"] = sha
    row["data_uri"] = data_uri
    row["deps"] = deps
    row["snapshot_uri"] = snap
    row["successful"] = successful
    row["latest_flow_name"] = flow
    row["latest_run_id"] = run_id
    row["latest_snapshot_uri"] = snap
    if run.get("origin_run_id"):
        row["origin_run_id"] = str(run["origin_run_id"])
    if run.get("yk_app_id"):
        row["yk_app_id"] = str(run["yk_app_id"])
    if run.get("yk_queue"):
        row["yk_queue"] = str(run["yk_queue"])
    if run.get("steps"):
        row["steps"] = str(run["steps"])

    upkeep = run.get("upkeep")
    if upkeep is not None and not isinstance(upkeep, dict):
        raise WarehouseError("upkeep walk must be a dict")
    assess = assess_upkeep(upkeep, row, expected=expects_upkeep(run))
    row.update(assess)

    for name, val in (
        ("snapshot_uri", snap),
        ("code_package", code),
        ("code_package_sha", sha),
        ("data_uri", data_uri),
        ("deps", deps),
        ("successful", successful),
        ("yk_app_id", row.get("yk_app_id") or ""),
        ("yk_queue", row.get("yk_queue") or ""),
        ("assessment", assess.get("assessment") or ""),
        ("upkeep_nominal", assess.get("upkeep_nominal") or ""),
        ("upkeep_fsm", assess.get("upkeep_fsm") or ""),
    ):
        if val:
            row[run_attr(flow, run_id, name)] = val
    return row


def snapshot_understanding(product: dict[str, Any], event: dict[str, Any]) -> str:
    """ACP addendum: net result of the flow as the snapshot(s) retained."""
    snaps = retained_snapshots(product)
    lines = [
        "",
        "## Snapshot retained (net result of the flow)",
        "",
        "This product **is** Metaflow's per-run immutable snapshot. A run is",
        "complete only when **code**, **data**, and **deps** landed on RustFS.",
        "",
        f"- Flow: `{product.get('flow_name') or '—'}`",
        f"- Run: `{product.get('run_id') or '—'}`",
        f"- Pathspec: `{product.get('pathspec') or '—'}`",
        f"- Snapshot URI: `{product.get('snapshot_uri') or '—'}`",
        f"- Code package: `{product.get('code_package') or '—'}`",
        f"- Code sha: `{product.get('code_package_sha') or '—'}`",
        f"- Data (CAS): `{product.get('data_uri') or '—'}`",
        f"- Deps: `{product.get('deps') or '(default environment — no @conda/@pypi lock)'}`",
        f"- Object store: `{product.get('object_store') or '—'}` "
        f"`{product.get('datastore_root') or ''}` @ `{product.get('rustfs_endpoint') or ''}`",
        f"- YK: app `{product.get('yk_app_id') or '—'}` queue `{product.get('yk_queue') or '—'}`",
        f"- tx: `{event.get('tx_id') or event.get('event_id') or '—'}`",
        "",
        "## ACP assessment (observe upkeep)",
        "",
        "Job: observe `data-product.tier-upkeep` and confirm it is **proceeding",
        "nominally**. Do not re-inventory. Holding is not failed and not done.",
        "",
        f"- Verdict: `{product.get('assessment') or '—'}`",
        f"- Phase: `{product.get('assessment_phase') or '—'}`",
        f"- Upkeep nominal: `{product.get('upkeep_nominal') or '—'}`",
        f"- Upkeep FSM: `{product.get('upkeep_fsm') or '—'}`",
        f"- ADD: `{product.get('upkeep_add') or '—'}`",
        f"- Settle: `{product.get('upkeep_settle') or '—'}`",
        f"- Review method: `{product.get('assessment_method') or DATA_PRODUCT_HISTORY_REVIEW}`",
        f"- Quality: {product.get('quality') or '—'}",
        f"- Lineage: {product.get('lineage') or '—'}",
        f"- Delta: {product.get('delta') or '—'}",
        f"- Observed: {product.get('assessment_ok') or '—'}",
        f"- Off-nominal: {product.get('assessment_off') or '(none)'}",
        "",
        f"Snapshots retained on this product ({len(snaps)}):",
    ]
    if snaps:
        for s in snaps:
            lines.append(
                f"- `{s['pathspec']}` → `{s['snapshot_uri']}`"
                + (f" sha={s['code_package_sha']}" if s.get("code_package_sha") else "")
            )
    else:
        lines.append("- (none projected yet — this tx is the first assert)")
    lines.append("")
    return "\n".join(lines)


def record_snapshot(
    run: dict[str, Any],
    *,
    warehouse: Any | None = None,
    catalog: Path | None = None,
    env: dict[str, str] | None = None,
    profile: dict[str, Any] | None = None,
    fail_off_nominal: bool = True,
) -> tuple[dict[str, Any], Path]:
    """Assert this run's snapshot + ACP assessment into details/tx/hx."""
    from signals.ops.history import product_by_id, review

    facts = facts_from_run(run, catalog_row=product_by_id(PRODUCT_ID, catalog), env=env, profile=profile)
    verdict = facts.get("assessment") or ""
    summary = (
        f"{facts['flow_name']}/{facts['run_id']} retained {facts['snapshot_uri']}"
        f" assessment={verdict}"
    )
    ev, path = review(
        PRODUCT_ID,
        kind="snapshot",
        summary=summary,
        catalog=catalog,
        warehouse=warehouse,
        product=facts,
        source="metaflow",
    )
    ev["assessment"] = verdict
    ev["upkeep_nominal"] = facts.get("upkeep_nominal")
    if fail_off_nominal and verdict == "off_nominal":
        raise WarehouseError(
            f"upkeep off-nominal: {facts.get('assessment_off') or 'unspecified'}"
        )
    return ev, path


def record_from_current(
    current: Any,
    extra: dict[str, Any] | None = None,
    **kw: Any,
) -> tuple[dict[str, Any], Path]:
    return record_snapshot(run_from_current(current, extra), **kw)
