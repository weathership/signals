"""signals.ops — procedure FSM, Brier ledger, named methods.

    uv run python -m signals.ops redeploy
    uv run python -m signals.ops methods
    uv run python -m signals.ops method [name]
    uv run python -m signals.ops report
    uv run python -m signals.ops risk --state apps_completing
    uv run python -m signals.ops review-product ID [--kind updated] [--summary ...]
    uv run python -m signals.ops record-snapshot --flow NAME --run-id ID
    uv run python -m signals.ops warehouse-apply
    uv run python -m signals.ops tier-upkeep
"""

from __future__ import annotations

import argparse
import json
import sys

from signals.ops.history import review as review_product, seed_details
from signals.ops.ledger import ObservationLedger
from signals.ops.probes import method_forecasts
from signals.ops.procedures import METHODS, K8S_PRODUCT_REDEPLOY, describe_method, get_method
from signals.ops.redeploy import run as run_redeploy
from signals.ops.tier_upkeep import walk as walk_tier_upkeep


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="signals-ops")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("redeploy", help="Walk k8s.product-redeploy (just redeploy)")
    sub.add_parser("methods", help="List registered methods")
    mth = sub.add_parser("method", help="Show one method (FSM + well-posed probes)")
    mth.add_argument("name", nargs="?", default=K8S_PRODUCT_REDEPLOY)
    rpt = sub.add_parser("report", help="Brier report from the observation ledger")
    rpt.add_argument(
        "--axis",
        choices=("method", "implicit", "both"),
        default="both",
        help="Score by method FSM, implicit K8s/YK FSM, or both",
    )
    rsk = sub.add_parser("risk", help="Forecast probe risk at a FSM state")
    rsk.add_argument("--state", default="apps_completing")
    rsk.add_argument("--method", default=K8S_PRODUCT_REDEPLOY)
    rsk.add_argument("--implicit-fsm", default="")
    rsk.add_argument("--implicit-state", default="")
    rev = sub.add_parser(
        "review-product",
        help="Record a data-product history event and write the ACP brief",
    )
    rev.add_argument("product_id")
    rev.add_argument("--kind", default="updated")
    rev.add_argument("--summary", default="")
    sub.add_parser(
        "warehouse-apply",
        help="Seed Iceberg details from JSON (RustFS SoR; never pglite)",
    )
    snap = sub.add_parser(
        "record-snapshot",
        help="Map one Metaflow run onto signals.metaflow.snapshots (RustFS only)",
    )
    snap.add_argument("--flow", required=True)
    snap.add_argument("--run-id", required=True)
    snap.add_argument("--code-package", default="")
    snap.add_argument("--code-sha", default="")
    snap.add_argument("--deps", default="")
    snap.add_argument("--yk-app-id", default="")
    snap.add_argument("--yk-queue", default="root.platform")
    sub.add_parser(
        "tier-upkeep",
        help="Plan data-product.tier-upkeep (ADD week / settle 4-week ranges)",
    )

    ns = p.parse_args(argv)
    if ns.cmd == "redeploy":
        return run_redeploy()
    if ns.cmd == "methods":
        for name in sorted(METHODS):
            print(name)
        return 0
    if ns.cmd == "method":
        try:
            fsm = get_method(ns.name)
        except KeyError as e:
            print(e, file=sys.stderr)
            return 2
        json.dump(describe_method(fsm), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if ns.cmd == "report":
        rows = ObservationLedger().report(axis=ns.axis)
        if not rows:
            print("(empty ledger)")
            return 0
        if ns.axis == "implicit":
            hdr = f"{'observer':<28} {'implicit':<28} {'n':>3} {'res':>3}  brier"
        elif ns.axis == "both":
            hdr = (
                f"{'observer':<28} {'method':<16} {'implicit':<24} "
                f"{'n':>3} {'res':>3}  brier"
            )
        else:
            hdr = f"{'observer':<28} {'state':<18} {'n':>3} {'res':>3}  brier"
        print(hdr)
        for r in rows:
            b = f"{r['brier']:.3f}" if r["brier"] is not None else "  —"
            if ns.axis == "implicit":
                impl = f"{r.get('implicit_fsm') or '—'}={r.get('implicit_state') or '—'}"
                print(
                    f"{str(r['observer']):<28} {impl:<28} "
                    f"{r['n']:>3} {r['resolved']:>3}  {b}"
                )
            elif ns.axis == "both":
                impl = f"{r.get('implicit_fsm') or '—'}={r.get('implicit_state') or '—'}"
                print(
                    f"{str(r['observer']):<28} {str(r.get('fsm_state') or '—'):<16} "
                    f"{impl:<24} {r['n']:>3} {r['resolved']:>3}  {b}"
                )
            else:
                print(
                    f"{str(r['observer']):<28} {str(r.get('fsm_state') or '—'):<18} "
                    f"{r['n']:>3} {r['resolved']:>3}  {b}"
                )
        return 0
    if ns.cmd == "risk":
        try:
            fsm = get_method(ns.method)
        except KeyError as e:
            print(e, file=sys.stderr)
            return 2
        if ns.state not in fsm.states:
            print(f"unknown state {ns.state!r}", file=sys.stderr)
            return 2
        fsm.current = ns.state
        led = ObservationLedger()
        rows = method_forecasts(led, fsm)
        if ns.implicit_fsm:
            extra = led.forecast_risk(
                "probe:yk-completed",
                ns.state,
                procedure=fsm.name,
                implicit_fsm=ns.implicit_fsm,
                implicit_state=ns.implicit_state or None,
            )
            rows.append(extra)
        json.dump(
            {
                "method": fsm.name,
                "state": ns.state,
                "holding": fsm.is_holding(),
                "probes": rows,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    if ns.cmd == "review-product":
        try:
            ev, brief = review_product(
                ns.product_id, kind=ns.kind, summary=ns.summary
            )
        except KeyError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"recorded {ev['product_id']} kind={ev['kind']}")
        print(f"brief {brief}")
        sys.stdout.write(brief.read_text(encoding="utf-8"))
        return 0
    if ns.cmd == "warehouse-apply":
        try:
            written = seed_details()
        except Exception as e:
            print(e, file=sys.stderr)
            return 2
        print("seeded", ", ".join(written) if written else "(already present)")
        return 0
    if ns.cmd == "record-snapshot":
        from signals.ops.metaflow_store import record_snapshot

        run = {
            "flow_name": ns.flow,
            "run_id": ns.run_id,
            "code_package": ns.code_package,
            "code_package_sha": ns.code_sha,
            "deps": ns.deps,
        }
        if ns.yk_app_id:
            run["yk_app_id"] = ns.yk_app_id
        if ns.yk_queue:
            run["yk_queue"] = ns.yk_queue
        try:
            ev, brief = record_snapshot(run)
        except Exception as e:
            print(e, file=sys.stderr)
            return 2
        print(f"recorded {ev['product_id']} kind={ev['kind']}")
        print(f"assessment {ev.get('assessment') or '—'} review={((ev.get('review') or {}).get('current'))}")
        print(f"brief {brief}")
        sys.stdout.write(brief.read_text(encoding="utf-8"))
        return 0
    if ns.cmd == "tier-upkeep":
        json.dump(walk_tier_upkeep(apply_sql=False), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
