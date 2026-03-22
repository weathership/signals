#!/usr/bin/env python3
"""Evaluate DST classification against the GitTables CTA benchmark.

Orchestrates:
1. Load gittables_columns.parquet via load_parquet_columns()
2. Build BFO-grounded taxonomy from gittables_taxonomy.py
3. Classify all target columns with EmbeddingClassifier + DST
4. Score against gittables_gt.json ground truth
5. Compute micro-F1, macro-F1, hierarchical accuracy, DST metrics

Usage:
    uv run python scripts/evaluate_gittables.py \\
        --data-dir build/datasets/gittables/ \\
        --output build/gittables_eval.parquet

    # Visualize results
    embedding-atlas build/gittables_eval.parquet --text embedding_text
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sigint.csv_loader import group_by_table, load_parquet_columns
from sigint.features import FEATURE_NAMES


def _load_ground_truth(gt_path: Path) -> dict[str, str]:
    """Load ground truth from JSON. Expects {"mappings": {"key": "label"}}."""
    with open(gt_path) as f:
        data = json.load(f)
    return data.get("mappings", data)


def _run_catboost_kfold(
    clf,
    records: list[dict],
    all_features,
    gt: dict[str, str],
    category_set,
    n_folds: int = 5,
) -> list[dict[str, float] | None]:
    """Run CatBoost k-fold CV and return out-of-fold probabilities.

    Follows the same augmented k-fold strategy as build_sigint_embeddings.py:
    training data is augmented with category reference embeddings so every
    class has >= 1 training sample even in sparse folds.

    Returns a list (parallel to records) of {code: probability} dicts,
    or None for columns without GT.
    """
    import numpy as np
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import LabelEncoder

    from sigint.embedding_classifier import build_embedding_text

    model = clf._get_model()
    by_code = category_set.by_code

    # Embed all column texts
    texts = []
    for rec, feat in zip(records, all_features):
        from sigint.sampler import ColumnSample
        sample = ColumnSample(
            column_name=rec["column_name"],
            column_type=rec["column_type"],
            values=rec["sample_values"],
        )
        texts.append(build_embedding_text(sample, features=feat))

    print("  Encoding column embeddings...")
    X_all = model.encode(texts, batch_size=clf._config.batch_size,
                         show_progress_bar=False)

    # Category reference embeddings (augmentation)
    cats = category_set.categories
    ref_texts = [c.embedding_text for c in cats]
    ref_codes = [c.code for c in cats]
    print(f"  Encoding {len(ref_texts)} category reference embeddings...")
    X_ref = model.encode(ref_texts, batch_size=clf._config.batch_size,
                         show_progress_bar=False)

    # Identify GT-labeled columns
    gt_indices = []
    gt_codes = []
    for i, rec in enumerate(records):
        gt_key = f"{rec['source_table']}.{rec['column_name']}"
        code = gt.get(gt_key, "")
        if code and code in by_code:
            gt_indices.append(i)
            gt_codes.append(code)

    # Build label encoder from union of GT + reference codes
    all_codes = sorted(set(gt_codes) | set(ref_codes))
    le = LabelEncoder()
    le.fit(all_codes)
    class_labels = le.classes_.tolist()

    y_gt = le.transform(gt_codes)
    y_ref = le.transform(ref_codes)
    X_gt = X_all[gt_indices]

    print(f"  GT-labeled: {len(gt_indices)} columns, {len(class_labels)} classes")

    # Determine effective folds
    from collections import Counter
    class_counts = Counter(y_gt)
    min_count = min(class_counts.values()) if class_counts else 0
    effective_folds = min(n_folds, max(2, min_count))
    print(f"  Using {effective_folds}-fold CV (min class size: {min_count})")

    # Out-of-fold probabilities
    oof_proba: list[dict[str, float] | None] = [None] * len(records)

    from catboost import CatBoostClassifier

    skf = StratifiedKFold(n_splits=effective_folds, shuffle=True, random_state=42)

    for fold, (train_idx, val_idx) in enumerate(skf.split(X_gt, y_gt), 1):
        # Augmented training: real training samples + ALL reference embeddings
        X_train = np.vstack([X_gt[train_idx], X_ref])
        y_train = np.concatenate([y_gt[train_idx], y_ref])
        X_val = X_gt[val_idx]

        cb = CatBoostClassifier(
            loss_function="MultiClass",
            classes_count=len(class_labels),
            depth=6,
            iterations=200,
            l2_leaf_reg=0.5,
            learning_rate=0.1,
            random_seed=42,
            verbose=0,
            posterior_sampling=True,
        )
        cb.fit(X_train, y_train)

        proba = cb.predict_proba(X_val)
        for j, vi in enumerate(val_idx):
            real_idx = gt_indices[vi]
            proba_dict = {}
            for k, p in enumerate(proba[j]):
                if p > 1e-6:
                    proba_dict[class_labels[k]] = float(p)
            oof_proba[real_idx] = proba_dict

        print(f"    Fold {fold}/{effective_folds} complete")

    # CatBoost standalone accuracy (for comparison)
    cb_correct = 0
    cb_total = 0
    for i, rec in enumerate(records):
        if oof_proba[i] is not None:
            gt_key = f"{rec['source_table']}.{rec['column_name']}"
            gt_code = gt.get(gt_key, "")
            if gt_code:
                pred_code = max(oof_proba[i], key=oof_proba[i].get)
                cb_total += 1
                if pred_code == gt_code:
                    cb_correct += 1

    if cb_total > 0:
        print(f"  CatBoost standalone accuracy: {cb_correct}/{cb_total} "
              f"({cb_correct/cb_total:.1%})")

    return oof_proba


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Evaluate DST classification on GitTables CTA benchmark",
    )
    p.add_argument(
        "--data-dir", required=True,
        help="Directory containing gittables_columns.parquet and gittables_gt.json",
    )
    p.add_argument(
        "--output",
        default="build/gittables_eval.parquet",
        help="Output parquet file path",
    )
    p.add_argument(
        "--embedding-model",
        default="all-MiniLM-L6-v2",
        help="SentenceTransformer model (default: all-MiniLM-L6-v2)",
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
        help="Disable name-match boost",
    )
    p.add_argument(
        "--sage-permutations",
        type=int,
        default=0,
        help="SAGE permutation count (default: 0 = skip)",
    )
    p.add_argument(
        "--catboost-folds",
        type=int,
        default=0,
        help="CatBoost k-fold CV folds (default: 0 = skip). "
             "Trains CatBoost on GT labels and adds as DST evidence.",
    )
    args = p.parse_args(argv)

    data_dir = Path(args.data_dir).expanduser()
    output = Path(args.output)

    # ── Load data ───────────────────────────────────────────────────
    columns_path = data_dir / "gittables_columns.parquet"
    gt_path = data_dir / "gittables_gt.json"

    if not columns_path.exists():
        print(f"Error: {columns_path} not found", file=sys.stderr)
        print("Run scripts/download_gittables_benchmark.py first.", file=sys.stderr)
        return 1
    if not gt_path.exists():
        print(f"Error: {gt_path} not found", file=sys.stderr)
        return 1

    print(f"Loading columns from {columns_path}...")
    records = load_parquet_columns(columns_path)
    print(f"  {len(records)} target columns loaded")

    gt = _load_ground_truth(gt_path)
    print(f"  {len(gt)} ground truth mappings")

    # ── Build taxonomy ──────────────────────────────────────────────
    # Import from config module (project root must be on sys.path)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config.sigint.gittables_taxonomy import gittables_category_set

    category_set = gittables_category_set()
    print(f"  Taxonomy: {len(category_set.categories)} leaves, "
          f"{len(category_set.all_categories)} total nodes")

    # ── Build classifier ────────────────────────────────────────────
    from sigint.embedding_classifier import (
        EmbeddingClassifier,
        EmbeddingClassifierConfig,
        build_embedding_text,
    )
    from sigint.features import ColumnFeatures, extract_features
    from sigint.sampler import ColumnSample

    cfg = EmbeddingClassifierConfig(
        model_name=args.embedding_model,
        confidence_threshold=args.threshold,
        name_match_boost=not args.no_name_boost,
    )
    clf = EmbeddingClassifier(cfg, category_set=category_set)

    # ── Feature extraction ──────────────────────────────────────────
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

    print(f"  Extracted features for {len(all_features)} columns")

    # ── CatBoost k-fold CV (optional) ──────────────────────────────
    oof_proba: list[dict[str, float] | None] = [None] * len(records)
    if args.catboost_folds > 0:
        print(f"\nRunning CatBoost {args.catboost_folds}-fold CV...")
        oof_proba = _run_catboost_kfold(
            clf, records, all_features, gt, category_set,
            n_folds=args.catboost_folds,
        )

    # ── Classify ────────────────────────────────────────────────────
    print(f"\nClassifying {len(records)} columns...")
    results: list[dict] = []
    total = len(records)

    for i, (rec, sample, features) in enumerate(
        zip(records, all_samples, all_features), 1
    ):
        classification = clf.classify(
            sample, features=features,
            catboost_proba=oof_proba[i - 1],
        )

        text = build_embedding_text(sample, features=features)
        sample_str = ", ".join(v[:80] for v in rec["sample_values"][:5])

        bel = 0.0
        pl = 0.0
        if classification is not None:
            bel = classification.belief_at(classification.category.code)
            pl = classification.plausibility_at(classification.category.code)

        # GT lookup: "table_id.column_name" format
        gt_key = f"{rec['source_table']}.{rec['column_name']}"
        gt_code = gt.get(gt_key, "")
        correct = ""
        if gt_code and classification is not None:
            correct = "correct" if classification.category.code == gt_code else "wrong"

        row: dict = {
            "embedding_text": text,
            "source_table": rec["source_table"],
            "column_name": rec["column_name"],
            "sample_values": sample_str,
            "column_kind": "data",
            "tag_code": classification.category.code if classification else "",
            "tag_label": classification.category.label if classification else "unclassified",
            "tag_abbrev": "",
            "confidence": classification.confidence if classification else 0.0,
            "boost": 0.0,
            "gt_code": gt_code,
            "correct": correct if correct else "no_gt",
            "ml_tag_code": "",
            "ml_tag_label": "",
            "ml_confidence": 0.0,
            "ml_correct": "no_gt",
            "belief": round(bel, 4),
            "plausibility": round(pl, 4),
            "uncertainty_gap": round(pl - bel, 4),
            "conflict": classification.conflict if classification else 0.0,
            "needs_clarification": classification.needs_clarification if classification else False,
        }

        # Evidence sources
        if classification is not None:
            src_summary = {}
            for src_name, ba in classification.source_masses.items():
                best_mass = 0.0
                for fe, m in ba.masses.items():
                    if len(fe.codes) == 1 and m > best_mass:
                        best_mass = m
                src_summary[src_name] = round(best_mass, 3)
            row["evidence_sources"] = json.dumps(src_summary)
        else:
            row["evidence_sources"] = ""

        # Belief path
        hcs = clf._get_hierarchical_cs()
        if classification is not None and hasattr(hcs, "ancestors"):
            path = []
            code = classification.category.code
            cat_obj = hcs.all_by_code.get(code)
            path.append({
                "code": code,
                "label": cat_obj.label if cat_obj else code,
                "bel": round(bel, 3),
                "pl": round(pl, 3),
            })
            for anc_code in hcs.ancestors(code):
                anc_bel = classification.belief_at(anc_code)
                anc_pl = classification.plausibility_at(anc_code)
                anc_cat = hcs.all_by_code.get(anc_code)
                path.append({
                    "code": anc_code,
                    "label": anc_cat.label if anc_cat else anc_code,
                    "bel": round(anc_bel, 3),
                    "pl": round(anc_pl, 3),
                })
            row["belief_path"] = json.dumps(path)
        else:
            row["belief_path"] = ""

        # feat_* and sage_* columns
        for fname in FEATURE_NAMES:
            row[f"feat_{fname}"] = features.feature_value(fname)
            row[f"sage_{fname}"] = 0.0

        results.append(row)

        if i % 100 == 0 or i == total:
            print(f"  [{i}/{total}] classified")

    # ── Evaluate ────────────────────────────────────────────────────
    from sklearn.metrics import f1_score

    y_true = []
    y_pred = []
    for row in results:
        if row["gt_code"] and row["tag_code"]:
            y_true.append(row["gt_code"])
            y_pred.append(row["tag_code"])

    evaluated = len(y_true)
    if evaluated == 0:
        print("\nNo ground truth matches found — check GT key format.", file=sys.stderr)
        return 1

    micro_f1 = f1_score(y_true, y_pred, average="micro", zero_division=0)
    macro_f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)
    exact_match = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    accuracy = exact_match / evaluated

    # Hierarchical accuracy: correct if predicted is ancestor or descendant of truth
    hier_correct = 0
    for t, p in zip(y_true, y_pred):
        if t == p:
            hier_correct += 1
            continue
        # Check if predicted is ancestor of truth or truth is ancestor of predicted
        t_ancestors = set(category_set.ancestors(t)) if t in category_set.all_by_code else set()
        p_ancestors = set(category_set.ancestors(p)) if p in category_set.all_by_code else set()
        if p in t_ancestors or t in p_ancestors:
            hier_correct += 1

    hier_accuracy = hier_correct / evaluated if evaluated > 0 else 0.0

    # DST uncertainty stats
    beliefs = [r["belief"] for r in results if r["belief"] > 0]
    gaps = [r["uncertainty_gap"] for r in results if r["belief"] > 0]
    conflicts = [r["conflict"] for r in results if r["belief"] > 0]
    clarification_count = sum(1 for r in results if r.get("needs_clarification", False))

    mean_bel = sum(beliefs) / len(beliefs) if beliefs else 0.0
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    mean_conflict = sum(conflicts) / len(conflicts) if conflicts else 0.0
    clarification_rate = clarification_count / len(results) if results else 0.0

    # ── Print results ───────────────────────────────────────────────
    print(f"\n{'='*60}")
    mode = "cosine + CatBoost + DST" if args.catboost_folds > 0 else "cosine-only"
    print(f"GITTABLES CTA BENCHMARK RESULTS ({mode})")
    print(f"{'='*60}")
    print(f"  Evaluated:             {evaluated} columns")
    print(f"  Exact match:           {exact_match}/{evaluated} ({accuracy:.1%})")
    print(f"  Micro-F1:              {micro_f1:.4f}")
    print(f"  Macro-F1:              {macro_f1:.4f}")
    print(f"  Hierarchical accuracy: {hier_accuracy:.4f}")
    print(f"{'='*60}")
    print(f"  Mean belief:           {mean_bel:.4f}")
    print(f"  Mean uncertainty gap:  {mean_gap:.4f}")
    print(f"  Mean conflict (K):     {mean_conflict:.4f}")
    print(f"  Clarification rate:    {clarification_rate:.1%}")
    print(f"{'='*60}")

    # SOTA comparison
    print(f"\n  SOTA Comparison (zero-shot CTA):")
    print(f"  {'Method':<30} {'Micro-F1':>10}")
    print(f"  {'-'*40}")
    print(f"  {'ArcheType-GPT4 (LLM)':<30} {'~0.86':>10}")
    print(f"  {'ChatGPT (LLM)':<30} {'~0.85':>10}")
    print(f"  {'SemTab 2021 winner':<30} {'~0.59':>10}")
    print(f"  {'DST evidence fusion (ours)':<30} {micro_f1:>10.4f}")
    print()

    # Per-type breakdown (top 10 worst)
    per_type_true: dict[str, list[str]] = {}
    for t, p in zip(y_true, y_pred):
        per_type_true.setdefault(t, []).append(p)

    type_f1s: list[tuple[str, float, int]] = []
    for label, preds in per_type_true.items():
        correct_count = sum(1 for p in preds if p == label)
        type_f1 = correct_count / len(preds)  # precision proxy
        type_f1s.append((label, type_f1, len(preds)))

    type_f1s.sort(key=lambda x: x[1])
    print("  Worst-performing types:")
    for label, f1, n in type_f1s[:10]:
        print(f"    {label:<25} {f1:.2f} (n={n})")

    # ── SAGE (optional) ─────────────────────────────────────────────
    sage_dict = None
    if args.sage_permutations > 0:
        import numpy as np

        from sigint.sage_analysis import run_sage_analysis

        cats = category_set.categories
        code_to_idx = {c.code: i for i, c in enumerate(cats)}

        eval_features = []
        pseudo_gt = []
        for res, feat in zip(results, all_features):
            if res["tag_code"] and res["tag_code"] in code_to_idx:
                eval_features.append(feat)
                pseudo_gt.append(code_to_idx[res["tag_code"]])

        if eval_features:
            print(f"\nRunning SAGE ({args.sage_permutations} permutations)...")
            sage_result = run_sage_analysis(
                all_features=eval_features,
                ground_truth_indices=np.array(pseudo_gt),
                classifier=clf,
                category_set=category_set,
                method_name="cosine",
                n_permutations=args.sage_permutations,
            )
            sage_dict = sage_result.to_dict()

            sage_importance = dict(
                zip(sage_result.feature_names, sage_result.importance_values)
            )
            for row in results:
                for fname in FEATURE_NAMES:
                    row[f"sage_{fname}"] = sage_importance.get(fname, 0.0)

            print("SAGE Feature Importance:")
            ranked = sorted(
                zip(sage_result.feature_names, sage_result.importance_values),
                key=lambda x: -abs(x[1]),
            )
            for name, imp in ranked:
                print(f"  {name:20s} {imp:+.4f}")

    # ── Write parquet ───────────────────────────────────────────────
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
        ("belief", pa.float64()),
        ("plausibility", pa.float64()),
        ("uncertainty_gap", pa.float64()),
        ("conflict", pa.float64()),
        ("needs_clarification", pa.bool_()),
        ("evidence_sources", pa.string()),
        ("belief_path", pa.string()),
    ]
    for fname in FEATURE_NAMES:
        schema_fields.append((f"feat_{fname}", pa.string()))
    for fname in FEATURE_NAMES:
        schema_fields.append((f"sage_{fname}", pa.float64()))

    schema = pa.schema(schema_fields)
    arrays = {}
    for col_name, col_type in schema_fields:
        if col_type == pa.float64():
            arrays[col_name] = pa.array(
                [r.get(col_name, 0.0) for r in results], type=pa.float64()
            )
        elif col_type == pa.bool_():
            arrays[col_name] = pa.array(
                [r.get(col_name, False) for r in results], type=pa.bool_()
            )
        else:
            arrays[col_name] = pa.array(
                [r.get(col_name, "") for r in results]
            )

    table = pa.table(arrays, schema=schema)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(output))
    print(f"\nWrote {len(results)} records to {output}")

    # ── Write report JSON ───────────────────────────────────────────
    report_path = output.with_suffix(".report.json")
    report = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "benchmark": "gittables-cta-dbpedia",
        "config": {
            "embedding_model": args.embedding_model,
            "confidence_threshold": args.threshold,
            "name_match_boost": not args.no_name_boost,
        },
        "n_columns": len(results),
        "n_evaluated": evaluated,
        "metrics": {
            "micro_f1": round(micro_f1, 4),
            "macro_f1": round(macro_f1, 4),
            "exact_match_accuracy": round(accuracy, 4),
            "hierarchical_accuracy": round(hier_accuracy, 4),
            "mean_belief": round(mean_bel, 4),
            "mean_uncertainty_gap": round(mean_gap, 4),
            "mean_conflict": round(mean_conflict, 4),
            "clarification_rate": round(clarification_rate, 4),
        },
        "sota_comparison": {
            "archetype_gpt4": 0.86,
            "chatgpt": 0.85,
            "semtab_2021_winner": 0.59,
            "dst_evidence_fusion": round(micro_f1, 4),
        },
        "sage": sage_dict,
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  {report_path.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
