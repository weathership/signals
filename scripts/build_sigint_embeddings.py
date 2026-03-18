#!/usr/bin/env python3
"""Build a classified parquet from meta-tagging CSVs for embedding-atlas visualization.

Reads CSV files from the meta-tagging dataset, filters out annotation/reference
columns, classifies each data column against the chosen taxonomy, and writes an
embedding-atlas-compatible parquet file.

Usage:
    uv run python scripts/build_sigint_embeddings.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --output build/sigint_embeddings.parquet

    # With annotation taxonomy + accuracy evaluation
    uv run python scripts/build_sigint_embeddings.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --taxonomy annotations \
        --output build/sigint_annotations.parquet

    # Visualize with embedding-atlas
    embedding-atlas build/sigint_embeddings.parquet --text embedding_text
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def _load_csv_columns(
    data_dir: Path,
) -> list[dict]:
    """Load all CSV files and extract data columns with sample values.

    Returns a list of dicts with keys: source_table, column_name, column_type,
    sample_values (list of up to 5 values), headers (ordered fieldnames).
    """
    from sigint.category_set import is_data_column

    records = []
    csv.field_size_limit(sys.maxsize)

    for csv_path in sorted(data_dir.glob("*.csv")):
        if csv_path.name in ("annotations.csv", "metadata.csv"):
            continue

        table_name = csv_path.stem  # e.g. "personal_data"

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                continue

            headers = list(reader.fieldnames)

            # Collect up to 5 values per column
            col_values: dict[str, list[str]] = {
                fn: [] for fn in reader.fieldnames
            }
            for i, row in enumerate(reader):
                if i >= 5:
                    break
                for fn in reader.fieldnames:
                    val = row.get(fn, "")
                    if val:
                        col_values[fn].append(val)

        for full_col_name in headers:
            # Column names are table-prefixed: "personal_data.payment_card_number"
            bare_name = full_col_name.split(".", 1)[-1] if "." in full_col_name else full_col_name

            if not is_data_column(bare_name):
                continue

            records.append({
                "source_table": table_name,
                "column_name": bare_name,
                "column_type": "STRING",
                "sample_values": col_values.get(full_col_name, []),
                "headers": headers,
            })

    return records


def _classify_columns(
    records: list[dict],
    classifier_type: str,
    category_set=None,
    api_key: str | None = None,
    embedding_model: str = "all-MiniLM-L6-v2",
    xgboost_model: str | None = None,
    confidence_threshold: float = 0.3,
    name_match_boost: bool = True,
) -> list[dict]:
    """Classify each column record and add tag fields."""
    from sigint.sampler import ColumnSample

    if classifier_type == "embedding":
        from sigint.embedding_classifier import (
            EmbeddingClassifier,
            EmbeddingClassifierConfig,
            build_embedding_text,
        )

        cfg = EmbeddingClassifierConfig(
            model_name=embedding_model,
            xgboost_model_path=xgboost_model,
            confidence_threshold=confidence_threshold,
            name_match_boost=name_match_boost,
        )
        clf = EmbeddingClassifier(cfg, category_set=category_set)
    elif classifier_type == "llm":
        from sigint.llm_classifier import LLMClassifier, LLMClassifierConfig

        cfg = LLMClassifierConfig(api_key=api_key)
        clf = LLMClassifier(cfg)
    else:
        raise ValueError(f"Unknown classifier: {classifier_type}")

    # For embedding text construction
    from sigint.embedding_classifier import build_embedding_text

    results = []
    total = len(records)
    for i, rec in enumerate(records, 1):
        sample = ColumnSample(
            column_name=rec["column_name"],
            column_type=rec["column_type"],
            values=rec["sample_values"],
        )

        classification = clf.classify(sample)

        text = build_embedding_text(sample)
        sample_str = ", ".join(v[:80] for v in rec["sample_values"][:5])

        row = {
            "embedding_text": text,
            "source_table": rec["source_table"],
            "column_name": rec["column_name"],
            "sample_values": sample_str,
            "tag_code": classification.category.code if classification else "",
            "tag_label": classification.category.label if classification else "unclassified",
            "tag_abbrev": getattr(classification.category, "abbrev", "") if classification else "",
            "confidence": classification.confidence if classification else 0.0,
            "boost": classification.boost if classification else 0.0,
        }
        results.append(row)

        label = row["tag_label"]
        conf = row["confidence"]
        abbrev = row["tag_abbrev"]
        tag = f"{abbrev} ({label})" if abbrev else label
        print(f"  [{i}/{total}] {rec['source_table']}.{rec['column_name']} → {tag} ({conf:.2f})")

    return results


def _evaluate_accuracy(
    results: list[dict],
    records: list[dict],
    category_set,
) -> None:
    """Compare classifier predictions to ground truth extracted from CSV headers."""
    from sigint.category_set import extract_ground_truth

    # Build ground truth from all unique header lists
    truth: dict[str, str] = {}
    seen_headers: set[int] = set()
    for rec in records:
        hdr_id = id(rec["headers"])
        if hdr_id not in seen_headers:
            seen_headers.add(hdr_id)
            truth.update(extract_ground_truth(rec["headers"], category_set))

    if not truth:
        print("\nNo ground truth extracted (annotation columns not found).")
        return

    correct = 0
    wrong = 0
    missing_truth = 0
    boost_assisted = 0  # correct AND had a boost
    boost_dependent = 0  # correct AND boost changed the winner
    misclassified: list[tuple[str, str, str, str]] = []

    for res, rec in zip(results, records):
        col = rec["column_name"]
        if col not in truth:
            missing_truth += 1
            continue

        expected_code = truth[col]
        predicted_code = res["tag_code"]
        boost_val = res.get("boost", 0.0)

        if predicted_code == expected_code:
            correct += 1
            if boost_val > 0:
                boost_assisted += 1
                # Boost-dependent: confidence minus boost would drop below
                # the raw cosine winner's score.  Conservative proxy: the
                # boost exceeds the margin over second place, or confidence
                # minus boost < threshold.  Simpler: just check if boost
                # is a significant fraction of total confidence.
                cosine_only = res["confidence"] - boost_val
                if cosine_only < res["confidence"] * 0.5:
                    boost_dependent += 1
        else:
            wrong += 1
            expected_cat = category_set.by_code.get(expected_code)
            expected_label = expected_cat.abbrev if expected_cat else expected_code
            misclassified.append((
                f"{rec['source_table']}.{col}",
                expected_label,
                res["tag_abbrev"] or res["tag_code"],
                f"{res['confidence']:.2f}",
            ))

    evaluated = correct + wrong
    accuracy = correct / evaluated * 100 if evaluated > 0 else 0
    boost_rate = boost_assisted / evaluated * 100 if evaluated > 0 else 0

    print(f"\n{'='*60}")
    print(f"ACCURACY REPORT")
    print(f"{'='*60}")
    print(f"  Evaluated:     {evaluated} columns (with ground truth)")
    print(f"  Skipped:       {missing_truth} columns (no ground truth)")
    print(f"  Correct:       {correct}")
    print(f"  Wrong:         {wrong}")
    print(f"  Accuracy:      {accuracy:.1f}%")
    print()
    print(f"  Boost-assisted:  {boost_assisted}/{evaluated} ({boost_rate:.1f}%)"
          f"  ← negative metric, optimize toward 0%")
    print(f"  Boost-dependent: {boost_dependent}/{evaluated}"
          f"  (boost > 50% of confidence)")

    if misclassified:
        print(f"\n  Misclassified ({len(misclassified)}):")
        for col, expected, predicted, conf in misclassified:
            print(f"    {col}: expected={expected}, got={predicted} (conf={conf})")

    print(f"{'='*60}")


def _write_parquet(records: list[dict], output: Path) -> None:
    """Write classified records to a parquet file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([
        ("embedding_text", pa.string()),
        ("source_table", pa.string()),
        ("column_name", pa.string()),
        ("sample_values", pa.string()),
        ("tag_code", pa.string()),
        ("tag_label", pa.string()),
        ("tag_abbrev", pa.string()),
        ("confidence", pa.float64()),
    ])

    arrays = {
        "embedding_text": pa.array([r["embedding_text"] for r in records]),
        "source_table": pa.array([r["source_table"] for r in records]),
        "column_name": pa.array([r["column_name"] for r in records]),
        "sample_values": pa.array([r["sample_values"] for r in records]),
        "tag_code": pa.array([r["tag_code"] for r in records]),
        "tag_label": pa.array([r["tag_label"] for r in records]),
        "tag_abbrev": pa.array([r["tag_abbrev"] for r in records]),
        "confidence": pa.array([r["confidence"] for r in records], type=pa.float64()),
    }

    table = pa.table(arrays, schema=schema)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(output))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build classified parquet from meta-tagging CSVs for embedding-atlas",
    )
    p.add_argument(
        "--data-dir",
        required=True,
        help="Path to meta-tagging CSV directory",
    )
    p.add_argument(
        "--output",
        default="build/sigint_embeddings.parquet",
        help="Output parquet file path",
    )
    p.add_argument(
        "--taxonomy",
        choices=["sigdg", "annotations"],
        default="sigdg",
        help="Taxonomy to classify against (default: sigdg)",
    )
    p.add_argument(
        "--classifier",
        choices=["embedding", "llm"],
        default="embedding",
        help="Classifier to use (default: embedding)",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (for --classifier llm)",
    )
    p.add_argument(
        "--embedding-model",
        default="all-MiniLM-L6-v2",
        help="SentenceTransformer model (default: all-MiniLM-L6-v2)",
    )
    p.add_argument(
        "--xgboost-model",
        default=None,
        help="Path to trained XGBoost model (.json)",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="Minimum confidence threshold (default: 0.3)",
    )
    p.add_argument(
        "--no-name-boost",
        action="store_true",
        help="Disable name-match boost (ablation: pure embedding similarity)",
    )

    args = p.parse_args(argv)
    data_dir = Path(args.data_dir).expanduser()
    output = Path(args.output)

    if not data_dir.is_dir():
        print(f"Error: {data_dir} is not a directory", file=sys.stderr)
        return 1

    # Build category set
    category_set = None
    if args.taxonomy == "annotations":
        from sigint.category_set import annotation_category_set
        ann_path = data_dir / "annotations.csv"
        if not ann_path.exists():
            print(f"Error: {ann_path} not found", file=sys.stderr)
            return 1
        category_set = annotation_category_set(ann_path)
        print(f"Loaded annotation taxonomy: {len(category_set.categories)} leaf categories")

    print(f"Loading columns from {data_dir}...")
    records = _load_csv_columns(data_dir)
    print(f"Found {len(records)} data columns")

    print(f"\nClassifying with {args.classifier} classifier ({args.taxonomy} taxonomy)...")
    name_boost = not args.no_name_boost
    classified = _classify_columns(
        records,
        classifier_type=args.classifier,
        category_set=category_set,
        api_key=args.api_key,
        embedding_model=args.embedding_model,
        xgboost_model=args.xgboost_model,
        confidence_threshold=args.threshold,
        name_match_boost=name_boost,
    )

    # Accuracy evaluation (when ground truth is available)
    if category_set is not None:
        _evaluate_accuracy(classified, records, category_set)

    _write_parquet(classified, output)
    print(f"\nWrote {len(classified)} records to {output}")

    # Summary
    labels: dict[str, int] = {}
    for r in classified:
        label = r["tag_label"]
        labels[label] = labels.get(label, 0) + 1
    print("\nLabel distribution:")
    for label, count in sorted(labels.items(), key=lambda x: -x[1]):
        print(f"  {label}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
