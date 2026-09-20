#!/usr/bin/env python3
"""Bounded Airflow backfill for gaius_theta_cycle.

Theta consolidates the ISO week that closed relative to each Monday 06:00
logical date. DAG catchup=False stays — unpausing must not dump every missed
week onto the LIGHT token. Historical weeks are one Airflow backfill with
max_active_runs=1 (and run-backwards so the most recent closed week goes first).

  uv run python scripts/theta_backfill.py --from-date 2026-08-03 --to-date 2026-09-14 --dry-run
  uv run python scripts/theta_backfill.py --from-date 2026-08-03 --to-date 2026-09-14

Does not talk to Gaius. Signals owns Airflow.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


DAG_ID = "gaius_theta_cycle"


def _iso_date(s: str) -> str:
    raw = (s or "").strip()
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-date", required=True, help="inclusive start (YYYY-MM-DD or ISO datetime)")
    p.add_argument("--to-date", required=True, help="inclusive end (YYYY-MM-DD or ISO datetime)")
    p.add_argument("--dag-id", default=DAG_ID)
    p.add_argument("--max-active-runs", type=int, default=1)
    p.add_argument(
        "--reprocess",
        default="failed",
        choices=("none", "failed", "completed"),
        help="Airflow reprocess behavior (default: failed)",
    )
    p.add_argument("--forwards", action="store_true", help="oldest interval first (default is latest first)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    from signals.engine.airflow_api import AirflowClient

    client = AirflowClient()
    body = client.create_backfill(
        args.dag_id,
        from_date=_iso_date(args.from_date),
        to_date=_iso_date(args.to_date),
        reprocess_behavior=args.reprocess,
        max_active_runs=max(1, int(args.max_active_runs)),
        run_backwards=not args.forwards,
        dry_run=bool(args.dry_run),
    )
    json.dump(body, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
