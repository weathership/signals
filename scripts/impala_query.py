#!/usr/bin/env python3
"""Impala HS2 client for Signals — Kerberos GSSAPI only.

Connects to $IMPALA_HS2_HOST (FQDN / SIGNALS_KRB_HOST), never 127.0.0.1 for
GSSAPI, so the SPN is impala/<host>@REALM matching .devenv/kdc/impala.keytab.

Usage:
  uv run python scripts/impala_query.py -q 'SELECT 1'
  uv run python scripts/impala_query.py -q 'SHOW TABLES' -o tables.txt
  uv run python scripts/impala_query.py -q 'SELECT * FROM t' -o t.tsv --header
"""
from __future__ import annotations

import argparse
import csv
import os
import sys


def _connect():
    # Shared Kerberos-only connector (no NOSASL)
    from signals.impala import impala_connect

    return impala_connect()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-q", "--query", required=True, help="SQL to run")
    p.add_argument("-o", "--output", help="Write TSV result (default: stdout)")
    p.add_argument(
        "--header",
        action="store_true",
        help="Include column names as first row",
    )
    p.add_argument(
        "--probe",
        action="store_true",
        help="Run SELECT 1 and exit (ignore -q body for readiness)",
    )
    args = p.parse_args(argv)

    try:
        conn = _connect()
    except Exception as e:
        print(f"ERROR: Impala GSSAPI connect failed: {e}", file=sys.stderr)
        print(
            "  Ensure: kinit (just kinit), Impala Kerberos on (devenv up), "
            "IMPALA_HS2_HOST=$SIGNALS_KRB_HOST",
            file=sys.stderr,
        )
        return 1

    sql = "SELECT 1" if args.probe else args.query
    try:
        cur = conn.cursor()
        cur.execute(sql)
        # DDL / statements with no result set
        try:
            rows = cur.fetchall()
            colnames = [d[0] for d in (cur.description or [])]
        except Exception:
            rows = []
            colnames = []
        cur.close()
        conn.close()
    except Exception as e:
        print(f"ERROR: query failed: {e}", file=sys.stderr)
        try:
            conn.close()
        except Exception:
            pass
        return 1

    out = open(args.output, "w", newline="") if args.output else sys.stdout
    try:
        w = csv.writer(out, delimiter="\t", lineterminator="\n")
        if args.header and colnames:
            w.writerow(colnames)
        for row in rows:
            w.writerow(["" if c is None else c for c in row])
    finally:
        if args.output:
            out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
