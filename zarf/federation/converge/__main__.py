"""CLI: python3 -m converge list|verify  (from zarf/federation)."""

from __future__ import annotations

import argparse
import sys

from .catalog import build_catalog


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="converge")
    p.add_argument("command", choices=("list", "verify"))
    args = p.parse_args(argv)
    catalog = build_catalog()

    if args.command == "list":
        for inv in catalog:
            print(f"{inv.tier:4} {inv.id:32} [{inv.layer.value}] {inv.title}")
        return 0

    failed = 0
    for inv in catalog:
        probe = inv.detect(None)
        tag = "ok" if probe.ok else "FAIL"
        if not probe.ok:
            failed += 1
        print(f"[{tag:4}] {inv.id}: {probe.detail}")
    print(f"\n{len(catalog) - failed}/{len(catalog)} OK", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
