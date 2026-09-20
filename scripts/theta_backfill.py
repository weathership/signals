#!/usr/bin/env python3
"""Bounded Theta backfill: daily LIGHT increments into a week-level artifact.

On-time Monday 06:00 still consolidates the previous ISO week in one run.
A long miss must not open that whole week (or many weeks) in one LIGHT
occupancy. Default increment is one UTC day: each run encodes that day's
thoughts and refines the *same* ``theta_consolidation_runs`` row for the
containing ISO week. The data product is the week consolidation, not a
stack of day slices.

DAG catchup stays false. ``gaius_theta_cycle.max_active_runs=1`` serializes
the daily runs.

  uv run python scripts/theta_backfill.py --from-date 2026-08-03 --to-date 2026-09-14 --dry-run
  uv run python scripts/theta_backfill.py --from-date 2026-08-03 --to-date 2026-09-14

  # One Monday run per week (the old coarse path):
  uv run python scripts/theta_backfill.py --weekly --from-date 2026-08-03 --to-date 2026-09-14

Does not talk to Gaius. Signals owns Airflow.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone


DAG_ID = "gaius_theta_cycle"


def _parse_day(s: str) -> date:
    raw = (s or "").strip()
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    return datetime.strptime(raw, "%Y-%m-%d").date()


def iso_week_of(d: date) -> str:
    cal = d.isocalendar()
    return f"{cal.year}-W{int(cal.week):02d}"


def daily_refine_windows(
    from_date: str, to_date: str, *, backwards: bool = True
) -> list[tuple[str, str]]:
    """(window_date, slice_id) for each UTC day. slice_id is the week artifact."""
    d0, d1 = _parse_day(from_date), _parse_day(to_date)
    if d1 < d0:
        d0, d1 = d1, d0
    out: list[tuple[str, str]] = []
    d = d0
    while d <= d1:
        out.append((d.isoformat(), iso_week_of(d)))
        d += timedelta(days=1)
    if backwards:
        out.reverse()
    return out


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
        help="Airflow reprocess behavior for --weekly (default: failed)",
    )
    p.add_argument("--forwards", action="store_true", help="oldest interval first (default is latest first)")
    p.add_argument(
        "--weekly",
        action="store_true",
        help="one Monday run per week (coarse). Default is one UTC day per run.",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if not args.weekly:
        windows = daily_refine_windows(
            args.from_date, args.to_date, backwards=not args.forwards
        )
        if args.dry_run:
            json.dump(
                {
                    "dag_id": args.dag_id,
                    "increment": "day",
                    "max_active_runs": max(1, int(args.max_active_runs)),
                    "runs": [
                        {"window_date": w, "slice_id": s, "run_id": f"theta_day_{w}"}
                        for w, s in windows
                    ],
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
            return 0
        from signals.engine.airflow_api import AirflowClient

        client = AirflowClient()
        created = []
        for window, slice_id in windows:
            logical = datetime.fromisoformat(window).replace(
                hour=6, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
            )
            created.append(
                client.trigger_dag_run(
                    args.dag_id,
                    f"theta_day_{window}",
                    {"window_date": window, "slice_id": slice_id},
                    logical_date=logical.isoformat(),
                )
            )
        json.dump({"increment": "day", "count": len(created), "runs": created}, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

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
