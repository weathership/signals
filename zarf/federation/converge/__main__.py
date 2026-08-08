"""CLI entry: python3 -m converge verify|list (from zarf/federation)."""

from __future__ import annotations

import argparse
import sys

from .catalog import build_catalog
from .model import Outcome


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="converge", description="signals-federation FSM")
    p.add_argument(
        "command",
        choices=("list", "verify"),
        help="list catalog or run detect-only verify (stubs until kube helpers land)",
    )
    args = p.parse_args(argv)
    catalog = build_catalog()

    if args.command == "list":
        for inv in catalog:
            print(f"{inv.tier:4} {inv.id:32} [{inv.layer.value}] {inv.title}")
        return 0

    # verify — detect only; no remediation yet
    failed = 0
    for inv in catalog:
        probe = inv.detect(None)
        status = "ok" if probe.ok else "FAIL"
        if not probe.ok:
            failed += 1
        print(f"[{status:4}] {inv.id}: {probe.detail or inv.title}")
    if failed:
        print(
            f"\n{failed}/{len(catalog)} invariants not OK "
            "(expected for scaffold — implement detect/remediate next)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
