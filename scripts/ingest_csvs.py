#!/usr/bin/env python3
"""Ingest CSVs → Impala → Atlas → SIGDG tag workflow.

Usage:
  uv run python scripts/ingest_csvs.py --data-dir ~/local/tmp/meta-tagging/
  uv run python scripts/ingest_csvs.py --data-dir /path/to/data --api-key $ANTHROPIC_API_KEY
  uv run python scripts/ingest_csvs.py --data-dir ~/local/tmp/meta-tagging/ --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Disable thrift C accelerator before importing impyla.
sys.modules.setdefault("thrift.protocol.fastbinary", None)
sys.modules.setdefault("thrift.protocol.fastproto", None)

from impala.dbapi import connect as impala_connect  # noqa: E402

from sigint.atlas_client import AtlasClient  # noqa: E402
from sigint.config import TaggingConfig  # noqa: E402
from sigint.llm_classifier import (  # noqa: E402
    LLMClassifier,
    LLMClassifierConfig,
    load_annotations,
)
from sigint.sampler import ColumnSample  # noqa: E402


def discover_csvs(data_dir: Path) -> list[Path]:
    """Find *_data.csv files, excluding annotations.csv."""
    csvs = sorted(data_dir.glob("*_data.csv"))
    if not csvs:
        # Fall back to any CSV that isn't annotations.csv
        csvs = sorted(
            p for p in data_dir.glob("*.csv")
            if p.name != "annotations.csv"
        )
    return csvs


def csv_to_impala(
    csv_path: Path,
    db_name: str,
    host: str,
    port: int,
    max_rows: int = 100,
) -> tuple[str, list[tuple[str, str]]]:
    """Create an Impala table from a CSV and insert rows.

    Returns (table_fqn, columns) where columns is [(name, type), ...].
    """
    table_name = csv_path.stem.lower().replace("-", "_")

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = []
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            rows.append(row)

    # Sanitize column names
    columns = []
    for h in headers:
        col = h.strip().lower().replace(" ", "_").replace("-", "_")
        col = "".join(c for c in col if c.isalnum() or c == "_")
        if not col or col[0].isdigit():
            col = f"col_{col}"
        columns.append((col, "STRING"))

    conn = impala_connect(host=host, port=port, auth_mechanism="NOSASL")
    try:
        cur = conn.cursor()

        # Ensure database exists
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")

        # Create table
        col_defs = ", ".join(f"{name} {typ}" for name, typ in columns)
        cur.execute(f"DROP TABLE IF EXISTS {db_name}.{table_name}")
        cur.execute(f"CREATE TABLE {db_name}.{table_name} ({col_defs})")

        # Insert rows
        for row in rows:
            # Pad or truncate row to match column count
            padded = row[:len(columns)]
            while len(padded) < len(columns):
                padded.append("")
            values = ", ".join(
                "'" + v.replace("'", "''") + "'" for v in padded
            )
            cur.execute(f"INSERT INTO {db_name}.{table_name} VALUES ({values})")

        table_fqn = f"{db_name}.{table_name}"
        print(f"  Created {table_fqn}: {len(columns)} columns, {len(rows)} rows")
        return table_fqn, columns
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Ingest CSVs into Impala, register in Atlas, classify with SIGDG"
    )
    p.add_argument("--data-dir", required=True, help="Directory with CSV files")
    p.add_argument("--db", default="sigint_ingest", help="Impala database name")
    p.add_argument("--impala-host", default="localhost")
    p.add_argument("--impala-port", type=int, default=21050)
    p.add_argument("--atlas-url", default="http://localhost:21010")
    p.add_argument("--api-key", default=None, help="Anthropic API key")
    p.add_argument("--model", default="claude-opus-4-6")
    p.add_argument("--max-rows", type=int, default=100, help="Max rows to ingest per CSV")
    p.add_argument("--dry-run", action="store_true", help="Classify only, skip Atlas writes")
    args = p.parse_args(argv)

    data_dir = Path(args.data_dir).expanduser().resolve()
    if not data_dir.is_dir():
        print(f"Error: {data_dir} is not a directory", file=sys.stderr)
        return 1

    # Discover CSVs
    csvs = discover_csvs(data_dir)
    if not csvs:
        print(f"No CSV files found in {data_dir}", file=sys.stderr)
        return 1
    print(f"Found {len(csvs)} CSV file(s) in {data_dir}")

    # Load vocabulary if annotations.csv exists
    annotations_path = data_dir / "annotations.csv"
    vocab = []
    if annotations_path.exists():
        vocab = load_annotations(annotations_path)
        print(f"Loaded {len(vocab)} vocabulary terms from annotations.csv")

    # Config for Atlas client
    cfg = TaggingConfig(
        impala_host=args.impala_host,
        impala_port=args.impala_port,
        atlas_url=args.atlas_url,
        dry_run=args.dry_run,
    )
    atlas = AtlasClient(cfg)

    # Setup classification types
    if not args.dry_run:
        result = atlas.ensure_classification_types()
        print(f"Classification types: {result['created']} created, "
              f"{result['existing']} existing")

    # Build classifier
    llm_cfg = LLMClassifierConfig(
        api_key=args.api_key,
        model=args.model,
        annotations_vocabulary=vocab,
    )
    classifier = LLMClassifier(llm_cfg)

    # Process each CSV
    report_lines = []
    for csv_path in csvs:
        print(f"\n{'='*60}")
        print(f"Processing: {csv_path.name}")

        # Step 1: Ingest into Impala
        table_fqn, columns = csv_to_impala(
            csv_path, args.db, args.impala_host, args.impala_port, args.max_rows
        )

        # Step 2: Register in Atlas
        if not args.dry_run:
            db_name, table_name = table_fqn.split(".", 1)
            atlas.register_table(db_name, table_name, columns)
            print(f"  Registered in Atlas: {table_fqn}")

        # Step 3: Sample and classify
        conn = impala_connect(
            host=args.impala_host, port=args.impala_port, auth_mechanism="NOSASL"
        )
        try:
            cur = conn.cursor()
            samples = []
            for col_name, col_type in columns:
                cur.execute(
                    f"SELECT DISTINCT CAST({col_name} AS STRING) "
                    f"FROM {table_fqn} WHERE {col_name} IS NOT NULL LIMIT 10"
                )
                values = [str(r[0]) for r in cur.fetchall() if r[0] is not None]
                samples.append(ColumnSample(
                    column_name=col_name, column_type=col_type, values=values,
                ))
        finally:
            conn.close()

        # Step 4: Classify each column
        for sample in samples:
            classification = classifier.classify(sample, siblings=samples)
            if classification:
                cat = classification.category
                line = (
                    f"  {table_fqn}.{sample.column_name} → "
                    f"{cat.label} ({classification.confidence:.2f}) "
                    f"[{classification.evidence}]"
                )
                print(line)
                report_lines.append(line)

                # Step 5: Apply tag in Atlas
                if not args.dry_run:
                    guid = atlas.find_column_guid(table_fqn, sample.column_name)
                    if guid:
                        atlas.apply_classification(
                            guid,
                            classification.atlas_type_name,
                            confidence=classification.confidence,
                            evidence=classification.evidence,
                        )
            else:
                print(f"  {table_fqn}.{sample.column_name} → (unclassified)")

    # Summary
    print(f"\n{'='*60}")
    print(f"Done. Processed {len(csvs)} file(s), "
          f"{len(report_lines)} column(s) classified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
