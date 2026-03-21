#!/usr/bin/env python3
"""Multi-stage classification pipeline with SAGE feature importance.

Three-stage pipeline:
  Stage 1: Feature Extraction   — ColumnSample → ColumnFeatures
  Stage 2: Classification       — ColumnFeatures → Classification
  Stage 3: Report + SAGE        — RunReport + optional SageResult

Usage:
    # Full pipeline
    uv run python scripts/run_pipeline.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --taxonomy annotations --threshold 0.25 \
        --output build/runs/

    # With SAGE analysis
    uv run python scripts/run_pipeline.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --taxonomy annotations --threshold 0.25 \
        --sage --output build/runs/

    # Ablation: disable name boost
    uv run python scripts/run_pipeline.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --taxonomy annotations --threshold 0.25 \
        --no-name-boost --sage --output build/runs/

    # Ablation: disable specific features
    uv run python scripts/run_pipeline.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --taxonomy annotations --threshold 0.25 \
        --disable-features sample_values sibling_context \
        --sage --output build/runs/
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from sigint.csv_loader import build_feature_mask, group_by_table, load_csv_columns


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Multi-stage classification pipeline with SAGE feature importance",
    )
    p.add_argument("--data-dir", required=True, help="Path to meta-tagging CSV directory")
    p.add_argument("--output", default="build/runs/", help="Output directory for run reports")
    p.add_argument(
        "--taxonomy",
        choices=["sigdg", "annotations"],
        default="sigdg",
        help="Taxonomy to classify against",
    )
    p.add_argument(
        "--method",
        choices=["cosine", "catboost"],
        default="cosine",
        help="Classification method",
    )
    p.add_argument("--embedding-model", default="all-MiniLM-L6-v2", help="SentenceTransformer model")
    p.add_argument("--model-path", default=None, help="Path to trained CatBoost model (.cbm)")
    p.add_argument("--threshold", type=float, default=0.3, help="Confidence threshold")
    p.add_argument("--no-name-boost", action="store_true", help="Disable name-match boost")
    p.add_argument(
        "--disable-features",
        nargs="*",
        default=None,
        help="Feature names to disable for ablation",
    )
    p.add_argument("--sage", action="store_true", help="Run SAGE feature importance analysis")
    p.add_argument("--sage-permutations", type=int, default=512, help="SAGE permutation count")

    args = p.parse_args(argv)
    data_dir = Path(args.data_dir).expanduser()
    output_dir = Path(args.output).expanduser()

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

    # ── Stage 1: Load + Feature Extraction ───────────────────────────
    print(f"Loading columns from {data_dir}...")
    records = load_csv_columns(data_dir)
    print(f"Found {len(records)} data columns")

    from sigint.features import FEATURE_NAMES, extract_features
    from sigint.sampler import ColumnSample

    feature_mask = build_feature_mask(args.disable_features)
    enabled_features = FEATURE_NAMES
    if feature_mask:
        enabled_features = [n for n, v in feature_mask.items() if v]
        print(f"Feature mask: {len(enabled_features)}/{len(FEATURE_NAMES)} features enabled")
        disabled = [n for n, v in feature_mask.items() if not v]
        print(f"  Disabled: {disabled}")

    by_table = group_by_table(records)

    all_samples: list[ColumnSample] = []
    all_features = []
    for rec in records:
        sample = ColumnSample(
            column_name=rec["column_name"],
            column_type=rec["column_type"],
            values=rec["sample_values"],
        )
        all_samples.append(sample)

        # Build sibling list from same table
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
    from sigint.embedding_classifier import (
        EmbeddingClassifier,
        EmbeddingClassifierConfig,
        build_embedding_text,
    )

    name_boost = not args.no_name_boost
    model_path = args.model_path if args.method == "catboost" else None
    cfg = EmbeddingClassifierConfig(
        model_name=args.embedding_model,
        model_path=model_path,
        confidence_threshold=args.threshold,
        name_match_boost=name_boost,
    )
    clf = EmbeddingClassifier(cfg, category_set=category_set)

    print(f"\nClassifying with {args.method} ({args.taxonomy} taxonomy)...")

    from sigint.run_report import ColumnResult

    column_results: list[ColumnResult] = []
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

        cr = ColumnResult(
            source_table=rec["source_table"],
            column_name=rec["column_name"],
            embedding_text=text,
            predicted_code=classification.category.code if classification else "",
            predicted_label=(
                classification.category.label if classification else "unclassified"
            ),
            confidence=classification.confidence if classification else 0.0,
            boost=classification.boost if classification else 0.0,
            evidence=classification.evidence if classification else "",
        )
        column_results.append(cr)

        tag = cr.predicted_label
        abbrev = getattr(classification.category, "abbrev", "") if classification else ""
        if abbrev:
            tag = f"{abbrev} ({tag})"
        print(f"  [{i}/{total}] {rec['source_table']}.{rec['column_name']} -> {tag} ({cr.confidence:.2f})")

    # ── Ground truth evaluation ──────────────────────────────────────
    from sigint.run_report import AccuracyMetrics

    accuracy: AccuracyMetrics | None = None

    if category_set is not None:
        from sigint.category_set import extract_ground_truth

        truth: dict[str, str] = {}
        seen_headers: set[int] = set()
        for rec in records:
            hdr_id = id(rec["headers"])
            if hdr_id not in seen_headers:
                seen_headers.add(hdr_id)
                truth.update(extract_ground_truth(rec["headers"], category_set))

        if truth:
            correct = 0
            wrong = 0
            boost_assisted = 0
            boost_dependent = 0
            misclassified: list[dict] = []

            for cr, rec in zip(column_results, records):
                col = rec["column_name"]
                if col not in truth:
                    continue
                expected_code = truth[col]
                cr.ground_truth_code = expected_code

                if cr.predicted_code == expected_code:
                    correct += 1
                    cr.correct = True
                    if cr.boost > 0:
                        boost_assisted += 1
                        cosine_only = cr.confidence - cr.boost
                        if cosine_only < cr.confidence * 0.5:
                            boost_dependent += 1
                else:
                    wrong += 1
                    cr.correct = False
                    expected_cat = category_set.by_code.get(expected_code)
                    misclassified.append({
                        "column": f"{rec['source_table']}.{col}",
                        "expected": expected_cat.abbrev if expected_cat else expected_code,
                        "predicted": cr.predicted_code,
                        "confidence": cr.confidence,
                    })

            evaluated = correct + wrong
            acc = correct / evaluated if evaluated > 0 else 0
            accuracy = AccuracyMetrics(
                total_evaluated=evaluated,
                correct=correct,
                wrong=wrong,
                accuracy=round(acc, 4),
                boost_assisted=boost_assisted,
                boost_dependent=boost_dependent,
                misclassified=misclassified,
            )

            boost_rate = boost_assisted / evaluated * 100 if evaluated > 0 else 0
            print(f"\n{'='*60}")
            print("ACCURACY REPORT")
            print(f"{'='*60}")
            print(f"  Evaluated:       {evaluated} columns")
            print(f"  Correct:         {correct}")
            print(f"  Wrong:           {wrong}")
            print(f"  Accuracy:        {acc:.1%}")
            print(f"  Boost-assisted:  {boost_assisted}/{evaluated} ({boost_rate:.1f}%)")
            print(f"  Boost-dependent: {boost_dependent}/{evaluated}")
            if misclassified:
                print(f"\n  Misclassified ({len(misclassified)}):")
                for m in misclassified:
                    print(f"    {m['column']}: expected={m['expected']}, "
                          f"got={m['predicted']} (conf={m['confidence']:.2f})")
            print(f"{'='*60}")

    # ── Label distribution ───────────────────────────────────────────
    label_dist: dict[str, int] = {}
    for cr in column_results:
        label_dist[cr.predicted_label] = label_dist.get(cr.predicted_label, 0) + 1

    # ── Stage 3: SAGE Analysis ───────────────────────────────────────
    sage_results: list[dict] = []

    if args.sage:
        if accuracy is None or accuracy.total_evaluated == 0:
            print("\nSkipping SAGE: no ground truth available for evaluation.")
        else:
            import numpy as np

            from sigint.sage_analysis import run_sage_analysis

            # Build ground truth index array for evaluated columns
            cats = (category_set or clf._category_set).categories
            code_to_idx = {c.code: i for i, c in enumerate(cats)}

            eval_features = []
            gt_indices = []
            for cr, feat in zip(column_results, all_features):
                if cr.ground_truth_code and cr.ground_truth_code in code_to_idx:
                    eval_features.append(feat)
                    gt_indices.append(code_to_idx[cr.ground_truth_code])

            if eval_features:
                print(f"\nRunning SAGE analysis ({args.sage_permutations} permutations, "
                      f"{len(eval_features)} samples)...")
                sage_result = run_sage_analysis(
                    all_features=eval_features,
                    ground_truth_indices=np.array(gt_indices),
                    classifier=clf,
                    category_set=category_set or clf._category_set,
                    method_name=args.method,
                    feature_mask=feature_mask,
                    n_permutations=args.sage_permutations,
                )
                sage_results.append(sage_result.to_dict())

                print("\nSAGE Feature Importance:")
                ranked = sorted(
                    zip(sage_result.feature_names, sage_result.importance_values),
                    key=lambda x: -abs(x[1]),
                )
                for name, imp in ranked:
                    print(f"  {name:20s} {imp:+.4f}")

    # ── Build and write report ───────────────────────────────────────
    from sigint.run_report import RunConfig, RunReport

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = RunReport(
        timestamp=ts,
        config=RunConfig(
            taxonomy=args.taxonomy,
            classifier_method=args.method,
            embedding_model=args.embedding_model,
            confidence_threshold=args.threshold,
            name_match_boost=name_boost,
            feature_set=enabled_features,
        ),
        columns=column_results,
        accuracy=accuracy,
        sage_results=sage_results,
        label_distribution=label_dist,
    )

    run_dir = output_dir / ts
    report.write_json(run_dir / "report.json")
    report.write_parquet(run_dir / "columns.parquet")

    print(f"\nRun report written to {run_dir}/")
    print(f"  report.json    ({len(column_results)} columns)")
    print(f"  columns.parquet")

    return 0


if __name__ == "__main__":
    sys.exit(main())
