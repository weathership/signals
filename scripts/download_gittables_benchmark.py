#!/usr/bin/env python3
"""Download and prepare the GitTables CTA benchmark dataset.

Downloads from Zenodo record 5706316:
  - tables.zip (CSV tables inside tables/ subdirectory)
  - dbpedia_gt.csv (ground truth with annotation_label)
  - dbpedia_targets.csv (target column indices)
  - dbpedia_labels.csv (122 DBpedia property labels)

Extracts column metadata and writes:
  - gittables_columns.parquet (pipeline input)
  - gittables_gt.json (ground truth mappings)

Usage:
    uv run python scripts/download_gittables_benchmark.py \\
        --output build/datasets/gittables/
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

ZENODO_RECORD = "5706316"
ZENODO_BASE = f"https://zenodo.org/records/{ZENODO_RECORD}/files"

FILES = {
    "tables": f"{ZENODO_BASE}/tables.zip",
    "gt": f"{ZENODO_BASE}/dbpedia_gt.csv",
    "targets": f"{ZENODO_BASE}/dbpedia_targets.csv",
    "labels": f"{ZENODO_BASE}/dbpedia_labels.csv",
}

# Python type inference for CSV values
_NUMERIC_THRESHOLD = 0.8  # fraction of values that parse as numeric


def _infer_column_type(values: list[str]) -> str:
    """Infer a simplified type from sample values."""
    if not values:
        return "STRING"

    numeric_count = 0
    int_count = 0
    bool_values = {"true", "false", "0", "1", "yes", "no"}
    bool_count = 0

    for v in values:
        v_stripped = v.strip()
        if v_stripped.lower() in bool_values:
            bool_count += 1
        try:
            float(v_stripped.replace(",", ""))
            numeric_count += 1
            if v_stripped.isdigit() or (v_stripped.startswith("-") and v_stripped[1:].isdigit()):
                int_count += 1
        except (ValueError, OverflowError):
            pass

    n = len(values)
    if bool_count == n:
        return "BOOL"
    if numeric_count >= n * _NUMERIC_THRESHOLD:
        return "INT" if int_count == numeric_count else "FLOAT"
    return "STRING"


def simplify_arrow_type(arrow_type) -> str:
    """Map an Arrow type to a simplified type string."""
    type_str = str(arrow_type).lower()
    base = type_str.split("[")[0].split("(")[0].strip()

    _MAP = {
        "int8": "INT", "int16": "INT", "int32": "INT", "int64": "INT",
        "uint8": "INT", "uint16": "INT", "uint32": "INT", "uint64": "INT",
        "float16": "FLOAT", "float32": "FLOAT", "float64": "FLOAT",
        "float": "FLOAT", "double": "FLOAT", "half_float": "FLOAT",
        "decimal128": "FLOAT", "decimal256": "FLOAT",
        "utf8": "STRING", "large_utf8": "STRING", "string": "STRING",
        "large_string": "STRING",
        "bool_": "BOOL", "bool": "BOOL", "boolean": "BOOL",
        "timestamp": "TIMESTAMP", "date32": "TIMESTAMP", "date64": "TIMESTAMP",
    }

    if base in _MAP:
        return _MAP[base]
    for key, val in _MAP.items():
        if key in base:
            return val
    return "STRING"


def _download_file(url: str, desc: str) -> bytes:
    """Download a file from a URL, showing progress."""
    import requests

    print(f"  Downloading {desc}...")
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()

    chunks = []
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    for chunk in resp.iter_content(chunk_size=65536):
        chunks.append(chunk)
        downloaded += len(chunk)
        if total > 0:
            pct = downloaded / total * 100
            print(f"\r    {downloaded / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB ({pct:.0f}%)", end="")
    print()
    return b"".join(chunks)


def _load_csv_from_bytes(data: bytes) -> list[dict]:
    """Parse CSV from bytes into a list of dicts."""
    text = data.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Download GitTables CTA benchmark from Zenodo",
    )
    p.add_argument(
        "--output", required=True,
        help="Output directory for benchmark files",
    )
    p.add_argument(
        "--max-samples", type=int, default=5,
        help="Max non-null sample values per column (default: 5)",
    )
    args = p.parse_args(argv)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    import pyarrow as pa
    import pyarrow.parquet as pq

    # ── Download files ──────────────────────────────────────────────
    print("Downloading GitTables CTA benchmark from Zenodo...")

    tables_zip_bytes = _download_file(FILES["tables"], "tables.zip")
    gt_bytes = _download_file(FILES["gt"], "dbpedia_gt.csv")
    targets_bytes = _download_file(FILES["targets"], "dbpedia_targets.csv")
    labels_bytes = _download_file(FILES["labels"], "dbpedia_labels.csv")

    # ── Parse metadata CSVs ─────────────────────────────────────────
    # dbpedia_gt.csv columns: (index), table_id, target_column, annotation_id, annotation_label
    # dbpedia_targets.csv columns: (index), table_id, target_column
    # dbpedia_labels.csv columns: (index), annotation_id, annotation_label

    gt_rows = _load_csv_from_bytes(gt_bytes)
    targets_rows = _load_csv_from_bytes(targets_bytes)
    labels_rows = _load_csv_from_bytes(labels_bytes)

    # Labels: annotation_label values
    label_set = {r["annotation_label"].strip() for r in labels_rows if r.get("annotation_label")}
    print(f"  Labels: {len(label_set)} DBpedia types")

    # Targets: (table_id, col_idx_str) pairs
    target_set: set[tuple[str, str]] = set()
    for row in targets_rows:
        tid = (row.get("table_id") or "").strip()
        cidx = (row.get("target_column") or "").strip()
        if tid and cidx:
            target_set.add((tid, cidx))
    print(f"  Targets: {len(target_set)} target columns")

    # GT: (table_id, col_idx_str) → annotation_label
    gt_map: dict[tuple[str, str], str] = {}
    for row in gt_rows:
        tid = (row.get("table_id") or "").strip()
        cidx = (row.get("target_column") or "").strip()
        label = (row.get("annotation_label") or "").strip()
        if tid and cidx and label:
            gt_map[(tid, cidx)] = label
    print(f"  Ground truth: {len(gt_map)} mappings")

    # ── Build table_id → zip filename mapping ───────────────────────
    # GT uses table IDs like "GitTables_1501_dbpedia"
    # Zip contains "tables/GitTables_1501.csv"
    # We need to map from GT table_id → zip entry name

    with zipfile.ZipFile(io.BytesIO(tables_zip_bytes)) as zf:
        csv_names = [n for n in zf.namelist()
                     if n.endswith(".csv") and not n.startswith("__MACOSX")]
        print(f"  Found {len(csv_names)} CSV tables in archive")

        # Build lookup: stem (e.g. "GitTables_1501") → zip entry path
        zip_by_stem: dict[str, str] = {}
        for name in csv_names:
            stem = Path(name).stem  # "GitTables_1501"
            zip_by_stem[stem] = name

        # Collect all unique table IDs from targets
        gt_table_ids = {tid for tid, _ in target_set}
        print(f"  Unique table IDs in targets: {len(gt_table_ids)}")

        # Map GT table_id → zip stem by stripping "_dbpedia"/"_schema" suffix
        def _gt_id_to_stem(gt_id: str) -> str:
            for suffix in ("_dbpedia", "_schema"):
                if gt_id.endswith(suffix):
                    return gt_id[:-len(suffix)]
            return gt_id

        # ── Extract tables and build column records ─────────────────
        print("Extracting tables and building column metadata...")

        column_records: list[dict] = []
        gt_mappings: dict[str, str] = {}
        tables_processed = 0
        tables_skipped = 0

        for gt_table_id in sorted(gt_table_ids):
            stem = _gt_id_to_stem(gt_table_id)
            zip_entry = zip_by_stem.get(stem)
            if zip_entry is None:
                tables_skipped += 1
                continue

            # Read CSV from zip
            try:
                csv_bytes = zf.read(zip_entry)
                text = csv_bytes.decode("utf-8", errors="replace")
                reader = csv.reader(io.StringIO(text))
                all_rows = list(reader)
            except Exception as e:
                print(f"    Warning: skipping {zip_entry}: {e}", file=sys.stderr)
                tables_skipped += 1
                continue

            if len(all_rows) < 2:
                tables_skipped += 1
                continue

            tables_processed += 1
            header = all_rows[0]
            data_rows = all_rows[1:]

            # Get target columns for this table
            table_targets = {
                cidx for tid, cidx in target_set if tid == gt_table_id
            }

            for col_idx_str in sorted(table_targets):
                col_idx = int(col_idx_str)
                if col_idx >= len(header):
                    continue

                col_name = header[col_idx]

                # Sample up to N non-null values
                sample_values: list[str] = []
                for row in data_rows:
                    if col_idx < len(row):
                        val = row[col_idx].strip()
                        if val and len(sample_values) < args.max_samples:
                            sample_values.append(val)
                    if len(sample_values) >= args.max_samples:
                        break

                col_type = _infer_column_type(sample_values)

                # Sibling column names
                siblings = [h for i, h in enumerate(header) if i != col_idx]

                column_records.append({
                    "source_table": gt_table_id,
                    "column_name": col_name,
                    "column_type": col_type,
                    "sample_values": json.dumps(sample_values),
                    "sibling_columns": json.dumps(siblings),
                })

                # GT mapping
                gt_key = (gt_table_id, col_idx_str)
                if gt_key in gt_map:
                    gt_mappings[f"{gt_table_id}.{col_name}"] = gt_map[gt_key]

            if tables_processed % 200 == 0:
                print(f"    Processed {tables_processed} tables...")

    print(f"  Tables processed: {tables_processed}, skipped: {tables_skipped}")
    print(f"  Column records: {len(column_records)}")
    print(f"  GT mappings: {len(gt_mappings)}")

    # ── Write gittables_columns.parquet ─────────────────────────────
    columns_path = output_dir / "gittables_columns.parquet"
    schema = pa.schema([
        ("source_table", pa.string()),
        ("column_name", pa.string()),
        ("column_type", pa.string()),
        ("sample_values", pa.string()),
        ("sibling_columns", pa.string()),
    ])

    arrays = {
        "source_table": pa.array([r["source_table"] for r in column_records]),
        "column_name": pa.array([r["column_name"] for r in column_records]),
        "column_type": pa.array([r["column_type"] for r in column_records]),
        "sample_values": pa.array([r["sample_values"] for r in column_records]),
        "sibling_columns": pa.array([r["sibling_columns"] for r in column_records]),
    }

    out_table = pa.table(arrays, schema=schema)
    pq.write_table(out_table, str(columns_path))
    print(f"\nWrote {columns_path} ({len(column_records)} columns)")

    # ── Write gittables_gt.json ─────────────────────────────────────
    gt_path = output_dir / "gittables_gt.json"
    with open(gt_path, "w") as f:
        json.dump({"mappings": gt_mappings}, f, indent=2)
    print(f"Wrote {gt_path} ({len(gt_mappings)} mappings)")

    # ── Summary ─────────────────────────────────────────────────────
    unique_labels = set(gt_mappings.values())
    print(f"\nUnique GT types: {len(unique_labels)}")
    if unique_labels:
        for label in sorted(unique_labels):
            count = sum(1 for v in gt_mappings.values() if v == label)
            print(f"  {label}: {count}")
    print("Done.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
