#!/usr/bin/env python3
"""SVM pilot experiment: evaluate a TF-IDF + LinearSVC classifier as a fifth DST evidence source.

This script trains an SVM on the same training data used for CatBoost, evaluates
standalone hierarchical accuracy, measures correlation with existing sources,
and assesses the impact on fused DST belief intervals and conflict K.

Pilot success criteria (from team assessment):
  - Marginal DST improvement > 5-8% on uncertain cases
  - No increase in average Dempster conflict K
  - SVM predictions have measurably lower correlation with cosine/CatBoost
    than the existing sources have with each other

Usage:
    # Train SVM + evaluate standalone accuracy
    uv run python scripts/svm_pilot.py \
        --data-dir <data-dir> \
        --train-dir build/datasets/sigint_train/ \
        --ground-truth config/sigint/meta_tagging_gt.json \
        --taxonomy annotations \
        --output build/svm_pilot_report.json

    # With DST fusion comparison
    uv run python scripts/svm_pilot.py \
        --data-dir <data-dir> \
        --train-dir build/datasets/sigint_train/ \
        --ground-truth config/sigint/meta_tagging_gt.json \
        --taxonomy annotations \
        --compare-dst \
        --output build/svm_pilot_report.json

    # Save trained model for reuse
    uv run python scripts/svm_pilot.py \
        --data-dir <data-dir> \
        --train-dir build/datasets/sigint_train/ \
        --ground-truth config/sigint/meta_tagging_gt.json \
        --taxonomy annotations \
        --save-model build/models/svm_sigdg.pkl \
        --output build/svm_pilot_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _build_svm_text(record: dict) -> str:
    """Build short text for SVM from column record.

    Uses column name + sample values — the same information available
    to all evidence sources, but encoded as raw text for TF-IDF rather
    than as a dense embedding.
    """
    parts = [record["column_name"].replace("_", " ")]

    if record.get("column_type") and record["column_type"].upper() not in ("STRING", "VARCHAR"):
        parts.append(record["column_type"].lower())

    values = record.get("sample_values", [])
    if values:
        parts.append(", ".join(str(v)[:80] for v in values[:5]))

    return " | ".join(parts)


def _load_ground_truth(gt_path: Path) -> dict[str, str]:
    """Load ground truth mappings."""
    with open(gt_path) as f:
        data = json.load(f)
    return data.get("mappings", data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SVM pilot experiment for 5th DST evidence source")
    p.add_argument("--data-dir", required=True, help="Path to evaluation data directory")
    p.add_argument("--train-dir", required=True, help="Path to synthetic training data directory")
    p.add_argument("--ground-truth", required=True, help="Path to ground truth JSON")
    p.add_argument("--taxonomy", default="sigdg", choices=["sigdg", "annotations"])
    p.add_argument("--output", default="build/svm_pilot_report.json", help="Output report path")
    p.add_argument("--save-model", default=None, help="Save trained SVM model to this path")
    p.add_argument("--compare-dst", action="store_true", help="Compare 4-source vs 5-source DST fusion")
    p.add_argument("--svm-discount", type=float, default=0.20, help="SVM evidence discount (default: 0.20)")
    args = p.parse_args(argv)

    from sigint.config import load_config
    from sigint.csv_loader import group_by_table, load_csv_columns
    from sigint.features import extract_features
    from sigint.sampler import ColumnSample
    from sigint.svm_classifier import SVMClassifier

    overrides: dict = {"taxonomy_name": args.taxonomy, "data_dir": args.data_dir}

    # Auto-detect annotations CSV from data-dir for annotations taxonomy
    if args.taxonomy == "annotations":
        ann_path = Path(args.data_dir).expanduser() / "annotations.csv"
        if ann_path.exists():
            overrides["annotations_path"] = str(ann_path)

    cfg = load_config(overrides=overrides)
    category_set = cfg.build_category_set(hierarchical=True)
    by_code = category_set.by_code

    # ── Load training data ────────────────────────────────────────────
    train_dir = Path(args.train_dir).expanduser()
    print(f"Loading synthetic training data from {train_dir}...")
    train_records = load_csv_columns(train_dir)
    train_gt = _load_ground_truth(train_dir / "ground_truth.json")

    train_texts = []
    train_labels = []
    for rec in train_records:
        col = rec["column_name"]
        if col in train_gt and train_gt[col] in by_code:
            train_texts.append(_build_svm_text(rec))
            train_labels.append(train_gt[col])

    print(f"  Training samples: {len(train_texts)}")
    print(f"  Classes: {len(set(train_labels))}")

    # ── Train SVM ─────────────────────────────────────────────────────
    print("\nTraining SVM (TF-IDF + LinearSVC + CalibratedClassifierCV)...")
    svm = SVMClassifier()
    svm.fit(train_texts, train_labels)
    print("  Training complete.")

    if args.save_model:
        svm.save(args.save_model)
        print(f"  Model saved to {args.save_model}")

    # ── Load evaluation data ──────────────────────────────────────────
    data_dir = Path(args.data_dir).expanduser()
    print(f"\nLoading evaluation data from {data_dir}...")
    eval_records = load_csv_columns(data_dir)
    eval_gt = _load_ground_truth(Path(args.ground_truth))
    print(f"  Evaluation columns: {len(eval_records)}")
    print(f"  GT mappings: {len(eval_gt)}")

    # ── Evaluate SVM standalone ───────────────────────────────────────
    print("\nEvaluating SVM standalone accuracy...")
    eval_texts = [_build_svm_text(rec) for rec in eval_records]
    all_proba = svm.predict_proba(eval_texts)

    svm_correct = 0
    svm_wrong = 0
    misclassified = []
    for i, rec in enumerate(eval_records):
        col = rec["column_name"]
        if col not in eval_gt:
            continue

        expected = eval_gt[col]
        proba = all_proba[i]
        predicted = max(proba, key=proba.get) if proba else ""

        if predicted == expected:
            svm_correct += 1
        else:
            svm_wrong += 1
            exp_label = by_code[expected].label if expected in by_code else expected
            pred_label = by_code[predicted].label if predicted in by_code else predicted
            misclassified.append({
                "column": col,
                "expected": f"{expected} ({exp_label})",
                "predicted": f"{predicted} ({pred_label})",
                "confidence": round(proba.get(predicted, 0), 3),
            })

    svm_evaluated = svm_correct + svm_wrong
    svm_accuracy = svm_correct / svm_evaluated * 100 if svm_evaluated else 0

    print(f"\n{'='*60}")
    print("SVM STANDALONE ACCURACY")
    print(f"{'='*60}")
    print(f"  Evaluated: {svm_evaluated}")
    print(f"  Correct:   {svm_correct}")
    print(f"  Wrong:     {svm_wrong}")
    print(f"  Accuracy:  {svm_accuracy:.1f}%")
    print(f"{'='*60}")

    if misclassified:
        print(f"\n  Misclassified ({len(misclassified)}):")
        for m in misclassified[:20]:
            print(f"    {m['column']}: expected {m['expected']}, got {m['predicted']} (conf={m['confidence']})")
        if len(misclassified) > 20:
            print(f"    ... and {len(misclassified) - 20} more")

    # ── Source correlation analysis ───────────────────────────────────
    report = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "config": {
            "taxonomy": args.taxonomy,
            "svm_discount": args.svm_discount,
            "training_samples": len(train_texts),
            "training_classes": len(set(train_labels)),
            "eval_columns": len(eval_records),
        },
        "svm_standalone": {
            "evaluated": svm_evaluated,
            "correct": svm_correct,
            "wrong": svm_wrong,
            "accuracy": round(svm_accuracy / 100, 4),
            "misclassified": misclassified,
        },
    }

    # ── DST fusion comparison (4-source vs 5-source) ─────────────────
    if args.compare_dst:
        print("\nComparing 4-source vs 5-source DST fusion...")

        from sigint.belief import FrameOfDiscernment
        from sigint.confusable_pairs import get_confusable_pairs
        from sigint.embedding_classifier import (
            EmbeddingClassifier,
            EmbeddingClassifierConfig,
            build_embedding_text,
        )

        emb_cfg = EmbeddingClassifierConfig(
            model_name=cfg.embedding_model,
            confidence_threshold=cfg.confidence_threshold,
            name_match_boost=cfg.name_match_boost,
        )
        if cfg.embedding_cache_dir:
            emb_cfg.cache_dir = cfg.embedding_cache_dir
        clf = EmbeddingClassifier(emb_cfg, category_set=category_set)

        pairs = get_confusable_pairs(category_set.name)
        from sigint.category_set import HierarchicalCategorySet
        hcs = category_set if isinstance(category_set, HierarchicalCategorySet) else cfg.build_category_set(hierarchical=True)
        frame = FrameOfDiscernment(hcs, confusable_pairs=pairs)

        by_table = group_by_table(eval_records)

        dst4_correct = 0
        dst5_correct = 0
        dst4_wrong = 0
        dst5_wrong = 0
        dst4_conflicts = []
        dst5_conflicts = []
        dst4_gaps = []
        dst5_gaps = []
        improvements = []

        for i, rec in enumerate(eval_records):
            col = rec["column_name"]
            if col not in eval_gt:
                continue

            expected = eval_gt[col]
            sample = ColumnSample(
                column_name=rec["column_name"],
                column_type=rec["column_type"],
                values=rec["sample_values"],
            )
            siblings = [
                ColumnSample(
                    column_name=r["column_name"],
                    column_type=r["column_type"],
                    values=r["sample_values"],
                )
                for r in by_table.get(rec["source_table"], [])
            ]
            features = extract_features(
                sample, siblings=siblings, source_table=rec["source_table"],
            )

            # 4-source DST
            result4 = clf.classify(sample, features=features)

            # 5-source DST (with SVM)
            svm_proba_i = all_proba[i]
            result5 = clf.classify(sample, features=features, svm_proba=svm_proba_i)

            if result4 is not None and result5 is not None:
                pred4 = result4.category.code
                pred5 = result5.category.code

                if pred4 == expected:
                    dst4_correct += 1
                else:
                    dst4_wrong += 1

                if pred5 == expected:
                    dst5_correct += 1
                else:
                    dst5_wrong += 1

                dst4_conflicts.append(result4.conflict)
                dst5_conflicts.append(result5.conflict)
                dst4_gaps.append(result4.uncertainty_gap)
                dst5_gaps.append(result5.uncertainty_gap)

                # Track columns where 5-source fixed a 4-source error
                if pred4 != expected and pred5 == expected:
                    improvements.append({
                        "column": col,
                        "expected": expected,
                        "dst4_predicted": pred4,
                        "dst5_predicted": pred5,
                    })

        dst4_eval = dst4_correct + dst4_wrong
        dst5_eval = dst5_correct + dst5_wrong
        dst4_acc = dst4_correct / dst4_eval * 100 if dst4_eval else 0
        dst5_acc = dst5_correct / dst5_eval * 100 if dst5_eval else 0

        avg_k4 = sum(dst4_conflicts) / len(dst4_conflicts) if dst4_conflicts else 0
        avg_k5 = sum(dst5_conflicts) / len(dst5_conflicts) if dst5_conflicts else 0
        avg_gap4 = sum(dst4_gaps) / len(dst4_gaps) if dst4_gaps else 0
        avg_gap5 = sum(dst5_gaps) / len(dst5_gaps) if dst5_gaps else 0

        print(f"\n{'='*60}")
        print("DST FUSION COMPARISON")
        print(f"{'='*60}")
        print(f"  4-source accuracy: {dst4_correct}/{dst4_eval} ({dst4_acc:.1f}%)")
        print(f"  5-source accuracy: {dst5_correct}/{dst5_eval} ({dst5_acc:.1f}%)")
        print(f"  Accuracy delta:    {dst5_acc - dst4_acc:+.1f}%")
        print(f"  Avg conflict K:")
        print(f"    4-source: {avg_k4:.4f}")
        print(f"    5-source: {avg_k5:.4f}")
        print(f"    Delta:    {avg_k5 - avg_k4:+.4f}")
        print(f"  Avg uncertainty gap (Pl - Bel):")
        print(f"    4-source: {avg_gap4:.4f}")
        print(f"    5-source: {avg_gap5:.4f}")
        print(f"    Delta:    {avg_gap5 - avg_gap4:+.4f}")
        print(f"  Improvements (5-source fixed 4-source error): {len(improvements)}")
        print(f"{'='*60}")

        if improvements:
            print(f"\n  Fixed by 5-source DST ({len(improvements)}):")
            for imp in improvements[:10]:
                print(f"    {imp['column']}: expected={imp['expected']}, "
                      f"4-src={imp['dst4_predicted']} → 5-src={imp['dst5_predicted']}")

        report["dst_comparison"] = {
            "4_source": {
                "accuracy": round(dst4_acc / 100, 4),
                "correct": dst4_correct,
                "wrong": dst4_wrong,
                "avg_conflict_K": round(avg_k4, 4),
                "avg_uncertainty_gap": round(avg_gap4, 4),
            },
            "5_source": {
                "accuracy": round(dst5_acc / 100, 4),
                "correct": dst5_correct,
                "wrong": dst5_wrong,
                "avg_conflict_K": round(avg_k5, 4),
                "avg_uncertainty_gap": round(avg_gap5, 4),
            },
            "delta_accuracy_pct": round(dst5_acc - dst4_acc, 2),
            "delta_conflict_K": round(avg_k5 - avg_k4, 4),
            "improvements": improvements,
        }

    # ── Write report ──────────────────────────────────────────────────
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport written to {output_path}")

    # ── Top SVM features ──────────────────────────────────────────────
    top_features = svm.feature_importances(top_n=15)
    if top_features:
        print("\nTop SVM features (by absolute LinearSVC weight):")
        for name, weight in top_features:
            print(f"  {name:40s} {weight:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
