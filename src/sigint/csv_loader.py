"""Shared CSV loading utilities for meta-tagging datasets.

Extracts column records from CSV files, builds feature masks for ablation,
and groups records by table for sibling context construction.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def load_csv_columns(data_dir: Path) -> list[dict]:
    """Load all CSV files and extract all columns with sample values.

    Returns a list of dicts with keys: source_table, column_name, column_type,
    sample_values (list of up to 5 values), headers (ordered fieldnames).

    All columns are included — row_id, annotation references (attr_*, ref_*,
    etc.), and data columns alike.  Filtering is the caller's responsibility.
    """
    records: list[dict] = []
    csv.field_size_limit(sys.maxsize)

    for csv_path in sorted(data_dir.glob("*.csv")):
        if csv_path.name in ("annotations.csv", "metadata.csv"):
            continue

        table_name = csv_path.stem

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                continue

            headers = list(reader.fieldnames)

            col_values: dict[str, list[str]] = {fn: [] for fn in reader.fieldnames}
            for i, row in enumerate(reader):
                if i >= 5:
                    break
                for fn in reader.fieldnames:
                    val = row.get(fn, "")
                    if val:
                        col_values[fn].append(val)

        for full_col_name in headers:
            bare_name = (
                full_col_name.split(".", 1)[-1]
                if "." in full_col_name
                else full_col_name
            )

            records.append({
                "source_table": table_name,
                "column_name": bare_name,
                "column_type": "STRING",
                "sample_values": col_values.get(full_col_name, []),
                "headers": headers,
            })

    return records


def build_feature_mask(
    disabled_features: list[str] | None,
) -> dict[str, bool] | None:
    """Build a feature mask from the list of disabled feature names.

    Returns None if no features are disabled, otherwise a dict mapping
    each feature name to True (enabled) or False (disabled).
    """
    if not disabled_features:
        return None
    from sigint.features import FEATURE_NAMES

    mask = {n: True for n in FEATURE_NAMES}
    for name in disabled_features:
        if name in mask:
            mask[name] = False
        else:
            print(
                f"Warning: unknown feature '{name}', ignoring. "
                f"Valid features: {FEATURE_NAMES}",
                file=sys.stderr,
            )
    return mask


def group_by_table(records: list[dict]) -> dict[str, list[dict]]:
    """Group column records by source table name.

    Returns a dict mapping table name to the list of records from that table.
    """
    by_table: dict[str, list[dict]] = {}
    for rec in records:
        by_table.setdefault(rec["source_table"], []).append(rec)
    return by_table
