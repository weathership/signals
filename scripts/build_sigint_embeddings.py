#!/usr/bin/env python3
"""Build a SAGE-enhanced classified parquet from meta-tagging CSVs.

Produces an embedding-atlas-compatible parquet with 30 columns:
  - embedding_text (feature-derived, for --text flag)
  - classification columns (tag_code, tag_label, confidence, etc.)
  - feat_* columns (11 transparency features, always present)
  - sage_* columns (11 SAGE importance values, always present)

SAGE always runs using classifier predictions as pseudo-ground-truth —
this measures which features drive classification decisions regardless of
whether external ground truth is available.

When --ground-truth is provided (LLM-generated column→code JSON), accuracy
is evaluated against that mapping.

Usage:
    # Standard run (SAGE always runs with pseudo-GT)
    uv run python scripts/build_sigint_embeddings.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --taxonomy annotations --threshold 0.25 \
        --output build/sigint_embeddings.parquet

    # With LLM ground truth for accuracy evaluation
    uv run python scripts/build_sigint_embeddings.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --taxonomy annotations --threshold 0.25 \
        --ground-truth config/sigint/meta_tagging_gt.json \
        --output build/sigint_embeddings.parquet

    # Feature ablation
    uv run python scripts/build_sigint_embeddings.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --taxonomy annotations --threshold 0.25 \
        --disable-features sample_values sibling_context \
        --output build/sigint_ablation.parquet

    # Visualize with embedding-atlas
    embedding-atlas build/sigint_embeddings.parquet --text embedding_text
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sigint.csv_loader import build_feature_mask, group_by_table, load_csv_columns
from sigint.features import FEATURE_NAMES


def _build_classifier(args, category_set):
    """Build the embedding classifier from CLI args."""
    from sigint.embedding_classifier import EmbeddingClassifier, EmbeddingClassifierConfig

    name_boost = not args.no_name_boost
    cfg = EmbeddingClassifierConfig(
        model_name=args.embedding_model,
        xgboost_model_path=args.xgboost_model,
        confidence_threshold=args.threshold,
        name_match_boost=name_boost,
    )
    return EmbeddingClassifier(cfg, category_set=category_set)


def _load_ground_truth(gt_path: Path) -> dict[str, str]:
    """Load LLM-provided ground truth from JSON.

    Expects either ``{"mappings": {"col": "code", ...}}`` or a flat
    ``{"col": "code", ...}`` dict.
    """
    with open(gt_path) as f:
        data = json.load(f)
    return data.get("mappings", data)


def _evaluate_accuracy(results, records, truth, category_set):
    """Evaluate accuracy and print report. Returns (correct, wrong, misclassified)."""
    correct = 0
    wrong = 0
    missing_truth = 0
    boost_assisted = 0
    boost_dependent = 0
    misclassified: list[dict] = []

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
                cosine_only = res["confidence"] - boost_val
                if cosine_only < res["confidence"] * 0.5:
                    boost_dependent += 1
        else:
            wrong += 1
            expected_cat = category_set.by_code.get(expected_code)
            expected_label = expected_cat.abbrev if expected_cat else expected_code
            misclassified.append({
                "column": f"{rec['source_table']}.{col}",
                "expected": expected_label,
                "predicted": res["tag_abbrev"] or res["tag_code"],
                "confidence": res["confidence"],
            })

    evaluated = correct + wrong
    accuracy = correct / evaluated * 100 if evaluated > 0 else 0
    boost_rate = boost_assisted / evaluated * 100 if evaluated > 0 else 0

    print(f"\n{'='*60}")
    print("ACCURACY REPORT")
    print(f"{'='*60}")
    print(f"  Evaluated:       {evaluated} columns (with ground truth)")
    print(f"  Skipped:         {missing_truth} columns (no ground truth)")
    print(f"  Correct:         {correct}")
    print(f"  Wrong:           {wrong}")
    print(f"  Accuracy:        {accuracy:.1f}%")
    print(f"  Boost-assisted:  {boost_assisted}/{evaluated} ({boost_rate:.1f}%)")
    print(f"  Boost-dependent: {boost_dependent}/{evaluated}")

    if misclassified:
        print(f"\n  Misclassified ({len(misclassified)}):")
        for m in misclassified:
            print(f"    {m['column']}: expected={m['expected']}, "
                  f"got={m['predicted']} (conf={m['confidence']:.2f})")

    print(f"{'='*60}")

    return {
        "total_evaluated": evaluated,
        "correct": correct,
        "wrong": wrong,
        "accuracy": round(accuracy / 100, 4) if evaluated > 0 else 0,
        "boost_assisted": boost_assisted,
        "boost_dependent": boost_dependent,
        "misclassified": misclassified,
    }


def _write_parquet(results: list[dict], output: Path) -> None:
    """Write 30-column parquet with feat_* and sage_* columns always present."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema_fields = [
        ("embedding_text", pa.string()),
        ("source_table", pa.string()),
        ("column_name", pa.string()),
        ("sample_values", pa.string()),
        ("tag_code", pa.string()),
        ("tag_label", pa.string()),
        ("tag_abbrev", pa.string()),
        ("confidence", pa.float64()),
        ("boost", pa.float64()),
    ]

    # feat_* columns (always string)
    for fname in FEATURE_NAMES:
        schema_fields.append((f"feat_{fname}", pa.string()))

    # sage_* columns (always float64)
    for fname in FEATURE_NAMES:
        schema_fields.append((f"sage_{fname}", pa.float64()))

    schema = pa.schema(schema_fields)

    arrays = {}
    for col_name, col_type in schema_fields:
        if col_type == pa.float64():
            arrays[col_name] = pa.array(
                [r.get(col_name, 0.0) for r in results], type=pa.float64()
            )
        else:
            arrays[col_name] = pa.array(
                [r.get(col_name, "") for r in results]
            )

    table = pa.table(arrays, schema=schema)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(output))


def _write_report_json(
    output: Path,
    args,
    accuracy_metrics: dict | None,
    sage_dict: dict | None,
    enabled_features: list[str],
    n_records: int,
    gt_source: str | None,
) -> None:
    """Write companion .report.json alongside the parquet."""
    report_path = output.with_suffix(".report.json")
    report = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "config": {
            "taxonomy": args.taxonomy,
            "embedding_model": args.embedding_model,
            "confidence_threshold": args.threshold,
            "name_match_boost": not args.no_name_boost,
            "feature_set": enabled_features,
            "disabled_features": args.disable_features or [],
            "sage_permutations": args.sage_permutations,
        },
        "n_columns": n_records,
        "ground_truth_source": gt_source,
        "sage_source": "pseudo",
        "accuracy": accuracy_metrics,
        "sage": sage_dict,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  {report_path.name}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build SAGE-enhanced classified parquet for embedding-atlas",
    )
    p.add_argument("--data-dir", required=True, help="Path to meta-tagging CSV directory")
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
        "--embedding-model",
        default="all-MiniLM-L6-v2",
        help="SentenceTransformer model (default: all-MiniLM-L6-v2)",
    )
    p.add_argument("--xgboost-model", default=None, help="Path to trained XGBoost model (.json)")
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
    p.add_argument(
        "--disable-features",
        nargs="*",
        default=None,
        help="Feature names to disable for ablation",
    )
    p.add_argument(
        "--sage-permutations",
        type=int,
        default=512,
        help="SAGE permutation count (default: 512)",
    )
    p.add_argument(
        "--ground-truth",
        default=None,
        help="Path to LLM ground truth JSON (column→code mappings)",
    )

    args = p.parse_args(argv)
    data_dir = Path(args.data_dir).expanduser()
    output = Path(args.output)

    if not data_dir.is_dir():
        print(f"Error: {data_dir} is not a directory", file=sys.stderr)
        return 1

    # ── Build category set ───────────────────────────────────────────
    category_set = None
    if args.taxonomy == "annotations":
        from sigint.category_set import annotation_category_set

        ann_path = data_dir / "annotations.csv"
        if not ann_path.exists():
            print(f"Error: {ann_path} not found", file=sys.stderr)
            return 1
        category_set = annotation_category_set(ann_path)
        print(f"Loaded annotation taxonomy: {len(category_set.categories)} leaf categories")

    # ── Feature mask ─────────────────────────────────────────────────
    feature_mask = build_feature_mask(args.disable_features)
    enabled_features = list(FEATURE_NAMES)
    if feature_mask:
        enabled_features = [n for n, v in feature_mask.items() if v]
        disabled = [n for n, v in feature_mask.items() if not v]
        print(f"Feature mask: {len(enabled_features)}/{len(FEATURE_NAMES)} features enabled")
        print(f"  Disabled: {disabled}")

    # ── Stage 1: Load + Feature Extraction ───────────────────────────
    print(f"Loading columns from {data_dir}...")
    records = load_csv_columns(data_dir)
    print(f"Found {len(records)} columns")

    from sigint.features import ColumnFeatures, extract_features
    from sigint.sampler import ColumnSample

    by_table = group_by_table(records)

    all_samples: list[ColumnSample] = []
    all_features: list[ColumnFeatures] = []
    for rec in records:
        sample = ColumnSample(
            column_name=rec["column_name"],
            column_type=rec["column_type"],
            values=rec["sample_values"],
        )
        all_samples.append(sample)

        siblings = [
            ColumnSample(
                column_name=r["column_name"],
                column_type=r["column_type"],
                values=r["sample_values"],
            )
            for r in by_table[rec["source_table"]]
        ]

        features = extract_features(
            sample,
            siblings=siblings,
            source_table=rec["source_table"],
        )
        all_features.append(features)

    print(f"Extracted features for {len(all_features)} columns")

    # ── Stage 2: Classification ──────────────────────────────────────
    from sigint.embedding_classifier import build_embedding_text

    clf = _build_classifier(args, category_set)

    print(f"\nClassifying ({args.taxonomy} taxonomy)...")
    results: list[dict] = []
    total = len(records)

    for i, (rec, sample, features) in enumerate(
        zip(records, all_samples, all_features), 1
    ):
        classification = clf.classify(
            sample, features=features, feature_mask=feature_mask
        )

        text = build_embedding_text(
            sample, features=features, feature_mask=feature_mask
        )
        sample_str = ", ".join(v[:80] for v in rec["sample_values"][:5])

        row: dict = {
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

        # feat_* columns — always present
        for fname in FEATURE_NAMES:
            row[f"feat_{fname}"] = features.feature_value(fname)

        # sage_* columns — initialized to 0.0, updated after SAGE runs
        for fname in FEATURE_NAMES:
            row[f"sage_{fname}"] = 0.0

        results.append(row)

        label = row["tag_label"]
        conf = row["confidence"]
        abbrev = row["tag_abbrev"]
        tag = f"{abbrev} ({label})" if abbrev else label
        print(f"  [{i}/{total}] {rec['source_table']}.{rec['column_name']} -> {tag} ({conf:.2f})")

    # ── Stage 3: Accuracy vs LLM ground truth (when provided) ────────
    accuracy_metrics: dict | None = None
    gt_source: str | None = None

    if args.ground_truth:
        gt = _load_ground_truth(Path(args.ground_truth))
        gt_source = "llm"
        accuracy_metrics = _evaluate_accuracy(results, records, gt, category_set)

    # ── Stage 4: SAGE (always — predictions as pseudo-GT) ────────────
    sage_dict: dict | None = None

    import numpy as np

    from sigint.sage_analysis import run_sage_analysis

    cats = (category_set or clf._category_set).categories
    code_to_idx = {c.code: i for i, c in enumerate(cats)}

    eval_features = []
    pseudo_gt = []
    for res, feat in zip(results, all_features):
        if res["tag_code"] and res["tag_code"] in code_to_idx:
            eval_features.append(feat)
            pseudo_gt.append(code_to_idx[res["tag_code"]])

    if eval_features:
        print(f"\nRunning SAGE analysis ({args.sage_permutations} permutations, "
              f"{len(eval_features)} samples, pseudo-GT)...")
        sage_result = run_sage_analysis(
            all_features=eval_features,
            ground_truth_indices=np.array(pseudo_gt),
            classifier=clf,
            category_set=category_set or clf._category_set,
            method_name="cosine",
            feature_mask=feature_mask,
            n_permutations=args.sage_permutations,
        )
        sage_dict = sage_result.to_dict()

        # Build sage importance lookup
        sage_importance = dict(
            zip(sage_result.feature_names, sage_result.importance_values)
        )

        # Update sage_* columns in results — same value for every row
        # (SAGE is a global importance measure, not per-sample)
        for row in results:
            for fname in FEATURE_NAMES:
                row[f"sage_{fname}"] = sage_importance.get(fname, 0.0)

        print("\nSAGE Feature Importance:")
        ranked = sorted(
            zip(sage_result.feature_names, sage_result.importance_values),
            key=lambda x: -abs(x[1]),
        )
        for name, imp in ranked:
            print(f"  {name:20s} {imp:+.4f}")
    else:
        print("\nSkipping SAGE: no classified columns.")

    # ── Write outputs ────────────────────────────────────────────────
    _write_parquet(results, output)
    print(f"\nWrote {len(results)} records to {output}")

    _write_report_json(
        output, args, accuracy_metrics, sage_dict, enabled_features, len(results),
        gt_source,
    )

    # ── Label distribution ───────────────────────────────────────────
    labels: dict[str, int] = {}
    for r in results:
        label = r["tag_label"]
        labels[label] = labels.get(label, 0) + 1
    print("\nLabel distribution:")
    for label, count in sorted(labels.items(), key=lambda x: -x[1]):
        print(f"  {label}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
