#!/usr/bin/env python3
"""Build a SAGE-enhanced classified parquet from meta-tagging CSVs.

Produces an embedding-atlas-compatible parquet with columns:
  - embedding_text (feature-derived, for --text flag)
  - classification columns (tag_code, tag_label, confidence, boost)
  - column_kind (data / annotation / row_id)
  - gt_code, correct (LLM ground truth evaluation)
  - ml_tag_code, ml_tag_label, ml_confidence, ml_correct (XGBoost CV)
  - feat_* columns (11 transparency features, always present)
  - sage_* columns (11 SAGE importance values, always present)

Three-signal comparison when --ground-truth is provided:
  1. Cosine (zero-shot embedding similarity)
  2. XGBoost (stratified k-fold CV, out-of-fold predictions)
  3. LLM GT (expert column→code mapping — the target)

SAGE always runs using classifier predictions as pseudo-ground-truth —
this measures which features drive classification decisions regardless of
whether external ground truth is available.

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

import re

from sigint.csv_loader import build_feature_mask, group_by_table, load_csv_columns
from sigint.features import FEATURE_NAMES

# Column-name prefixes that mark annotation/reference columns.
_ANNOTATION_PREFIXES = (
    "attr_", "ref_", "code_", "var_", "key_", "val_",
    "data_", "field_", "col_", "item_",
)


def _classify_column_kind(column_name: str) -> str:
    """Classify a column as 'data', 'annotation', or 'row_id'."""
    if column_name == "row_id":
        return "row_id"
    for prefix in _ANNOTATION_PREFIXES:
        if column_name.startswith(prefix):
            suffix = column_name[len(prefix):]
            if re.match(r"^[\d_]+$", suffix) and suffix[0].isdigit():
                return "annotation"
    return "data"


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


def _run_xgboost_cv(
    clf,
    records: list[dict],
    results: list[dict],
    gt: dict[str, str],
    category_set,
    n_folds: int = 5,
) -> list[dict]:
    """Run augmented k-fold ML CV and return per-column predictions.

    Strategy for this extreme low-data regime (174 classes, ~2 samples each):
    1. Augment training data with category reference embeddings (240 texts
       the cosine classifier uses as targets), giving >=3 samples per class.
    2. Use XGBoost with the augmented training set per fold.
    3. Only real data samples are held out for validation (reference texts
       are always in training), giving unbiased out-of-fold predictions.

    Returns a list (parallel to *records*) of dicts with keys:
        ml_tag_code, ml_tag_label, ml_confidence
    """
    import numpy as np
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import LabelEncoder
    from xgboost import XGBClassifier

    model = clf._get_model()
    by_code = category_set.by_code

    # Collect embedding texts (already computed in results)
    texts = [r["embedding_text"] for r in results]

    print("  Encoding column embeddings...")
    X_all = model.encode(texts, batch_size=32, show_progress_bar=False)

    # Build category reference augmentation embeddings
    cats = category_set.categories
    ref_texts = [c.embedding_text for c in cats]
    ref_codes = [c.code for c in cats]
    print(f"  Encoding {len(ref_texts)} category reference embeddings...")
    X_ref = model.encode(ref_texts, batch_size=32, show_progress_bar=False)

    # Identify GT-labeled real data indices
    gt_indices = []
    gt_codes = []
    for i, rec in enumerate(records):
        col = rec["column_name"]
        if col in gt and gt[col] in by_code:
            gt_indices.append(i)
            gt_codes.append(gt[col])

    # Build label encoder from union of GT codes + reference codes
    all_codes = sorted(set(gt_codes) | set(ref_codes))
    le = LabelEncoder()
    le.fit(all_codes)
    class_labels = le.classes_.tolist()

    y_gt = le.transform(gt_codes)
    y_ref = le.transform(ref_codes)
    X_gt = X_all[gt_indices]

    print(f"  GT-labeled: {len(gt_indices)} columns, {len(class_labels)} classes")
    print(f"  Reference augmentation: {len(ref_texts)} category embeddings")

    # Determine folds — check minimum class sizes in real data
    from collections import Counter
    class_counts = Counter(y_gt)
    min_count = min(class_counts.values()) if class_counts else 0
    effective_folds = min(n_folds, max(2, min_count))
    print(f"  Using {effective_folds}-fold CV (min class size in real data: {min_count})")

    # Out-of-fold predictions
    oof_codes = [""] * len(records)
    oof_labels = [""] * len(records)
    oof_confs = [0.0] * len(records)

    skf = StratifiedKFold(n_splits=effective_folds, shuffle=True, random_state=42)

    for fold, (train_idx, val_idx) in enumerate(skf.split(X_gt, y_gt), 1):
        # Augmented training: real training samples + ALL reference embeddings
        X_train = np.vstack([X_gt[train_idx], X_ref])
        y_train = np.concatenate([y_gt[train_idx], y_ref])
        X_val = X_gt[val_idx]

        xgb = XGBClassifier(
            objective="multi:softprob",
            num_class=len(class_labels),
            max_depth=6,
            n_estimators=200,
            reg_alpha=0.5,
            learning_rate=0.1,
            eval_metric="mlogloss",
            random_state=42,
            verbosity=0,
        )
        xgb.fit(X_train, y_train)

        proba = xgb.predict_proba(X_val)
        for j, vi in enumerate(val_idx):
            real_idx = gt_indices[vi]
            best = int(np.argmax(proba[j]))
            code = class_labels[best]
            oof_codes[real_idx] = code
            oof_labels[real_idx] = by_code[code].label if code in by_code else code
            oof_confs[real_idx] = float(proba[j][best])

        print(f"    Fold {fold}/{effective_folds} complete")

    # For non-GT columns (row_id), train on all GT + refs and predict
    non_gt_indices = [i for i in range(len(records)) if i not in set(gt_indices)]
    if non_gt_indices:
        X_full_train = np.vstack([X_gt, X_ref])
        y_full_train = np.concatenate([y_gt, y_ref])
        xgb_full = XGBClassifier(
            objective="multi:softprob",
            num_class=len(class_labels),
            max_depth=6,
            n_estimators=200,
            reg_alpha=0.5,
            learning_rate=0.1,
            eval_metric="mlogloss",
            random_state=42,
            verbosity=0,
        )
        xgb_full.fit(X_full_train, y_full_train)
        X_non = X_all[non_gt_indices]
        proba_non = xgb_full.predict_proba(X_non)
        for j, idx in enumerate(non_gt_indices):
            best = int(np.argmax(proba_non[j]))
            code = class_labels[best]
            oof_codes[idx] = code
            oof_labels[idx] = by_code[code].label if code in by_code else code
            oof_confs[idx] = float(proba_non[j][best])

    # Build per-row dicts
    ml_results = []
    for i in range(len(records)):
        ml_results.append({
            "ml_tag_code": oof_codes[i],
            "ml_tag_label": oof_labels[i],
            "ml_confidence": round(oof_confs[i], 4),
        })

    return ml_results


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
    """Write parquet with feat_*, sage_*, GT, and ML columns."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema_fields = [
        ("embedding_text", pa.string()),
        ("source_table", pa.string()),
        ("column_name", pa.string()),
        ("sample_values", pa.string()),
        ("column_kind", pa.string()),
        ("tag_code", pa.string()),
        ("tag_label", pa.string()),
        ("tag_abbrev", pa.string()),
        ("confidence", pa.float64()),
        ("boost", pa.float64()),
        ("gt_code", pa.string()),
        ("correct", pa.string()),
        ("ml_tag_code", pa.string()),
        ("ml_tag_label", pa.string()),
        ("ml_confidence", pa.float64()),
        ("ml_correct", pa.string()),
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
    ml_accuracy_metrics: dict | None,
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
            "ml_folds": args.ml_folds,
        },
        "n_columns": n_records,
        "ground_truth_source": gt_source,
        "sage_source": "pseudo",
        "accuracy_cosine": accuracy_metrics,
        "accuracy_ml": ml_accuracy_metrics,
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
    p.add_argument(
        "--ml-folds",
        type=int,
        default=5,
        help="Number of XGBoost CV folds (default: 5)",
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
            "column_kind": _classify_column_kind(rec["column_name"]),
            "tag_code": classification.category.code if classification else "",
            "tag_label": classification.category.label if classification else "unclassified",
            "tag_abbrev": getattr(classification.category, "abbrev", "") if classification else "",
            "confidence": classification.confidence if classification else 0.0,
            "boost": classification.boost if classification else 0.0,
            "gt_code": "",
            "correct": "no_gt",
            "ml_tag_code": "",
            "ml_tag_label": "",
            "ml_confidence": 0.0,
            "ml_correct": "no_gt",
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
    gt: dict[str, str] = {}

    if args.ground_truth:
        gt = _load_ground_truth(Path(args.ground_truth))
        gt_source = "llm"

        # Populate gt_code and correct columns
        for row, rec in zip(results, records):
            col = rec["column_name"]
            if col in gt:
                row["gt_code"] = gt[col]
                row["correct"] = "correct" if row["tag_code"] == gt[col] else "wrong"

        accuracy_metrics = _evaluate_accuracy(results, records, gt, category_set)

    # ── Stage 3.5: XGBoost CV predictions (when GT provided) ─────────
    ml_accuracy_metrics: dict | None = None

    if gt and category_set:
        print(f"\nRunning XGBoost {args.ml_folds}-fold CV...")
        ml_preds = _run_xgboost_cv(
            clf, records, results, gt, category_set,
            n_folds=args.ml_folds,
        )

        ml_correct_count = 0
        ml_wrong_count = 0
        for row, rec, ml in zip(results, records, ml_preds):
            row["ml_tag_code"] = ml["ml_tag_code"]
            row["ml_tag_label"] = ml["ml_tag_label"]
            row["ml_confidence"] = ml["ml_confidence"]

            col = rec["column_name"]
            if col in gt:
                is_correct = ml["ml_tag_code"] == gt[col]
                row["ml_correct"] = "correct" if is_correct else "wrong"
                if is_correct:
                    ml_correct_count += 1
                else:
                    ml_wrong_count += 1

        ml_evaluated = ml_correct_count + ml_wrong_count
        ml_acc = ml_correct_count / ml_evaluated * 100 if ml_evaluated else 0

        print(f"\n{'='*60}")
        print("ML (XGBoost CV) ACCURACY")
        print(f"{'='*60}")
        print(f"  Evaluated:  {ml_evaluated}")
        print(f"  Correct:    {ml_correct_count}")
        print(f"  Wrong:      {ml_wrong_count}")
        print(f"  Accuracy:   {ml_acc:.1f}%")
        print(f"{'='*60}")

        ml_accuracy_metrics = {
            "total_evaluated": ml_evaluated,
            "correct": ml_correct_count,
            "wrong": ml_wrong_count,
            "accuracy": round(ml_acc / 100, 4),
        }

    # ── Stage 4: SAGE (always — predictions as pseudo-GT) ────────────
    sage_dict: dict | None = None

    if args.sage_permutations <= 0:
        print("\nSAGE skipped (--sage-permutations 0).")
    else:
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
        output, args, accuracy_metrics, ml_accuracy_metrics, sage_dict,
        enabled_features, len(results), gt_source,
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
