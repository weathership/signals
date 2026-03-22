#!/usr/bin/env python3
"""Build a SAGE-enhanced classified parquet from meta-tagging CSVs.

Produces an embedding-atlas-compatible parquet with columns:
  - embedding_text (feature-derived, for --text flag)
  - classification columns (tag_code, tag_label, confidence, boost)
  - column_kind (data / annotation / row_id)
  - gt_code, correct (LLM ground truth evaluation)
  - ml_tag_code, ml_tag_label, ml_confidence, ml_correct (CatBoost CV)
  - feat_* columns (12 transparency features, always present)
  - sage_* columns (12 SAGE importance values, always present)

Three-signal comparison when --ground-truth is provided:
  1. Cosine (zero-shot embedding similarity)
  2. CatBoost (stratified k-fold CV, out-of-fold predictions)
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
        --output build/sigint_embeddings.parquet

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

from sigint.csv_loader import build_feature_mask, group_by_table, load_csv_columns, load_parquet_columns
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
        model_path=args.model_path,
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


def _run_catboost_cv(
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
    2. Use CatBoost with the augmented training set per fold.
    3. Only real data samples are held out for validation (reference texts
       are always in training), giving unbiased out-of-fold predictions.

    Returns a list (parallel to *records*) of dicts with keys:
        ml_tag_code, ml_tag_label, ml_confidence
    """
    import numpy as np
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import LabelEncoder
    from catboost import CatBoostClassifier

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
        cb_full = CatBoostClassifier(
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
        cb_full.fit(X_full_train, y_full_train)
        X_non = X_all[non_gt_indices]
        proba_non = cb_full.predict_proba(X_non)
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


# ── Pattern signal names for binary encoding ────────────────────────
_PATTERN_NAMES = [
    "email_pattern", "phone_pattern", "ssn_pattern", "ipv4_pattern",
    "uuid_pattern", "date_iso_pattern", "url_pattern", "credit_card_pattern",
]


def _encode_discrete_features(features_obj) -> list[float]:
    """Encode discrete ColumnFeatures into a numeric vector.

    Returns a vector of 11 floats (numeric features only):
      0: cardinality (int, 0 if None)
      1: null_ratio (float, 0 if None)
      2: value_entropy (float, 0 if None)
      3-10: pattern_signals (8 binary flags, one per pattern type)

    Note: value_description (12th SAGE feature) is a text feature
    incorporated via embedding text, not the discrete feature vector.
    """
    vec: list[float] = []
    vec.append(float(features_obj.cardinality or 0))
    vec.append(float(features_obj.null_ratio or 0))
    vec.append(float(features_obj.value_entropy or 0))

    # Pattern signals as binary flags
    patterns_set = set(features_obj.pattern_signals)
    for pname in _PATTERN_NAMES:
        vec.append(1.0 if pname in patterns_set else 0.0)

    return vec  # length = 11


def _run_catboost_train_eval(
    clf,
    train_records: list[dict],
    train_gt: dict[str, str],
    eval_records: list[dict],
    eval_results: list[dict],
    eval_features_list: list,
    eval_gt: dict[str, str],
    category_set,
    concat_features: bool = True,
) -> tuple[list[dict], dict]:
    """Train CatBoost on synthetic data, evaluate on real data.

    Strategy to bridge domain shift between synthetic and real embeddings:
    1. Augment synthetic training data with category reference embeddings
       (the same texts the cosine classifier targets).  These anchors live
       in the same embedding space as the real eval data, teaching CatBoost
       the mapping from embedding regions → categories.
    2. Scale discrete features (11 dims) so they compete with the 384-dim
       embedding rather than getting swamped.
    3. StandardScaler on full feature vector for stable gradient boosting.

    Returns:
        ml_preds: per-record prediction dicts for eval set
        accuracy_metrics: accuracy report dict
    """
    import numpy as np
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    from catboost import CatBoostClassifier

    from sigint.features import extract_features
    from sigint.sampler import ColumnSample

    model = clf._get_model()
    by_code = category_set.by_code

    # ── Prepare training data ──────────────────────────────────────

    # ── Value-only feature mask ──────────────────────────────────
    # Strips domain-specific features (column_name, source_table,
    # sibling_context) from embedding text.  The resulting "value-only"
    # embedding encodes only value patterns, cardinality, entropy, etc.
    # — features that are domain-invariant between synthetic and real data.
    _VALUE_ONLY_MASK = {
        "column_name": False,
        "column_type": True,
        "sample_values": True,
        "cardinality": True,
        "null_ratio": True,
        "value_entropy": True,
        "pattern_signals": True,
        "avg_value_length": True,
        "numeric_ratio": True,
        "sibling_context": False,
        "source_table": False,
        "value_description": True,
    }

    print("  Preparing synthetic training data...")
    train_full_texts = []
    train_vo_texts = []  # value-only
    train_codes = []
    train_feat_vecs = []

    train_by_table = group_by_table(train_records)

    for rec in train_records:
        col = rec["column_name"]
        if col not in train_gt:
            continue
        code = train_gt[col]
        if code not in by_code:
            continue

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
            for r in train_by_table[rec["source_table"]]
        ]
        features = extract_features(
            sample, siblings=siblings, source_table=rec["source_table"],
        )
        train_full_texts.append(features.to_embedding_text(None))
        train_vo_texts.append(features.to_embedding_text(_VALUE_ONLY_MASK))
        train_codes.append(code)
        if concat_features:
            train_feat_vecs.append(_encode_discrete_features(features))

    print(f"  Synthetic training samples: {len(train_full_texts)}")

    # ── Category reference augmentation ────────────────────────────
    cats = category_set.categories
    ref_texts = [c.embedding_text for c in cats]
    ref_codes = [c.code for c in cats]
    print(f"  Category reference augmentation: {len(ref_texts)} anchor embeddings")

    # ── Prepare evaluation data ────────────────────────────────────
    print("  Preparing evaluation data...")
    eval_full_texts = [r["embedding_text"] for r in eval_results]
    eval_vo_texts = [f.to_embedding_text(_VALUE_ONLY_MASK) for f in eval_features_list]
    eval_feat_vecs = []
    if concat_features:
        for feat_obj in eval_features_list:
            eval_feat_vecs.append(_encode_discrete_features(feat_obj))

    # ── Encode dual embeddings ─────────────────────────────────────
    # 1. Full embedding (name + values + table) — strong for data columns
    # 2. Value-only embedding (values + patterns only) — bridges domain
    #    shift for annotation columns where names are opaque
    all_train_texts = train_full_texts + ref_texts
    all_train_vo = train_vo_texts + ref_texts  # refs have no name/table anyway

    print(f"  Encoding {len(all_train_texts)} full training embeddings...")
    X_train_full_emb = model.encode(all_train_texts, batch_size=64, show_progress_bar=False)
    print(f"  Encoding {len(all_train_vo)} value-only training embeddings...")
    X_train_vo_emb = model.encode(all_train_vo, batch_size=64, show_progress_bar=False)

    print(f"  Encoding {len(eval_full_texts)} full eval embeddings...")
    X_eval_full_emb = model.encode(eval_full_texts, batch_size=64, show_progress_bar=False)
    print(f"  Encoding {len(eval_vo_texts)} value-only eval embeddings...")
    X_eval_vo_emb = model.encode(eval_vo_texts, batch_size=64, show_progress_bar=False)

    emb_dim = X_train_full_emb.shape[1]

    # ── Build feature matrix: [full_emb | value_only_emb | discrete] ──
    n_synth = len(train_full_texts)
    n_ref = len(ref_texts)

    if concat_features and train_feat_vecs:
        n_discrete = len(train_feat_vecs[0])
        scale_factor = float(np.sqrt(emb_dim / n_discrete))
        print(f"  Discrete features: {n_discrete} (scale={scale_factor:.1f}x)")

        # Training: synthetic + reference discrete features
        synth_disc = np.array(train_feat_vecs) * scale_factor
        ref_disc = np.zeros((n_ref, n_discrete))
        train_disc = np.vstack([synth_disc, ref_disc])

        eval_disc = np.array(eval_feat_vecs) * scale_factor

        X_train_combined = np.hstack([X_train_full_emb, X_train_vo_emb, train_disc])
        X_eval_combined = np.hstack([X_eval_full_emb, X_eval_vo_emb, eval_disc])
        total_dim = emb_dim * 2 + n_discrete
        print(f"  Feature dim: {total_dim} (full_emb={emb_dim} + vo_emb={emb_dim} + disc={n_discrete})")
    else:
        X_train_combined = np.hstack([X_train_full_emb, X_train_vo_emb])
        X_eval_combined = np.hstack([X_eval_full_emb, X_eval_vo_emb])

    # ── Cosine similarity features ─────────────────────────────────
    # Compute cosine similarity between each column's value-only embedding
    # and each category reference embedding.  These N_ref features encode
    # the cosine classifier's knowledge in a domain-invariant way (category
    # refs are the same for train and eval).
    from sklearn.metrics.pairwise import cosine_similarity

    # Extract reference value-only embeddings (last n_ref rows of X_train_vo_emb)
    X_ref_vo = X_train_vo_emb[n_synth:n_synth + n_ref]

    # Cosine sims: train (synth+ref), eval
    cos_train = cosine_similarity(
        X_train_vo_emb[:n_synth + n_ref], X_ref_vo,
    ).astype(np.float32)
    cos_eval = cosine_similarity(X_eval_vo_emb, X_ref_vo).astype(np.float32)

    print(f"  Cosine similarity features: {cos_train.shape[1]} (one per category ref)")

    # Append cosine sim features to combined feature matrices
    X_train_with_cos = np.hstack([X_train_combined, cos_train])
    X_eval_with_cos = np.hstack([X_eval_combined, cos_eval])

    print(f"  Total feature dim: {X_train_with_cos.shape[1]}")

    # ── Combine all training sources ───────────────────────────────
    X_train = X_train_with_cos
    y_train_codes = train_codes + ref_codes

    # ── Build label encoder ────────────────────────────────────────
    all_codes = sorted(set(y_train_codes))
    le = LabelEncoder()
    le.fit(all_codes)
    class_labels = le.classes_.tolist()
    y_train = le.transform(y_train_codes)

    # ── StandardScaler for stable gradient boosting ────────────────
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_eval = scaler.transform(X_eval_with_cos)

    print(f"  Classes: {len(class_labels)}, Training shape: {X_train.shape}")
    print(f"    Synthetic: {len(train_full_texts)}, Reference: {len(ref_texts)}")

    # ── Train CatBoost ─────────────────────────────────────────────
    cb = CatBoostClassifier(
        loss_function="MultiClass",
        classes_count=len(class_labels),
        depth=8,
        iterations=500,
        l2_leaf_reg=0.3,
        learning_rate=0.08,
        subsample=0.8,
        rsm=0.6,
        min_data_in_leaf=2,
        random_seed=42,
        verbose=0,
        posterior_sampling=True,
    )
    cb.fit(X_train, y_train)
    print("  CatBoost training complete.")

    # ── Predict on eval set ────────────────────────────────────────
    proba = cb.predict_proba(X_eval)

    # Pass 1: Raw CatBoost predictions for all columns
    raw_preds: list[tuple[str, float]] = []  # (code, confidence)
    for i in range(len(eval_records)):
        best = int(np.argmax(proba[i]))
        raw_preds.append((class_labels[best], float(proba[i][best])))

    # Pass 2: Paired column propagation — for each annotation column,
    # if its predecessor is a data column with a confident prediction,
    # propagate that prediction.  This exploits the dataset structure:
    # data columns and annotation columns are paired (annotation follows
    # its data column) and refer to the same category.
    pair_propagated = 0
    for i, rec in enumerate(eval_records):
        kind = _classify_column_kind(rec["column_name"])
        if kind != "annotation" or i == 0:
            continue
        prev_kind = _classify_column_kind(eval_records[i - 1]["column_name"])
        if prev_kind != "data":
            continue
        prev_code, prev_conf = raw_preds[i - 1]
        _, cur_conf = raw_preds[i]
        # Propagate when: data col is confident enough AND CatBoost is uncertain
        if prev_conf >= 0.35 and cur_conf < 0.50 and prev_code in by_code:
            raw_preds[i] = (prev_code, prev_conf * 0.9)
            pair_propagated += 1
    print(f"  Paired column propagation: {pair_propagated} annotation columns corrected")

    ml_preds: list[dict] = []
    ml_correct = 0
    ml_wrong = 0
    ml_correct_data = 0
    ml_wrong_data = 0
    ml_correct_ann = 0
    ml_wrong_ann = 0

    misclassified: list[dict] = []

    for i, rec in enumerate(eval_records):
        code, conf = raw_preds[i]
        kind = _classify_column_kind(rec["column_name"])
        label = by_code[code].label if code in by_code else code

        ml_preds.append({
            "ml_tag_code": code,
            "ml_tag_label": label,
            "ml_confidence": round(conf, 4),
        })

        col = rec["column_name"]
        if col in eval_gt:
            expected = eval_gt[col]
            is_correct = code == expected
            if is_correct:
                ml_correct += 1
                if kind == "data":
                    ml_correct_data += 1
                elif kind == "annotation":
                    ml_correct_ann += 1
            else:
                ml_wrong += 1
                if kind == "data":
                    ml_wrong_data += 1
                elif kind == "annotation":
                    ml_wrong_ann += 1
                exp_label = by_code[expected].label if expected in by_code else expected
                misclassified.append({
                    "column": col, "kind": kind,
                    "expected": f"{expected} ({exp_label})",
                    "predicted": f"{code} ({label})",
                    "confidence": round(conf, 3),
                })

    ml_evaluated = ml_correct + ml_wrong
    ml_acc = ml_correct / ml_evaluated * 100 if ml_evaluated else 0

    data_eval = ml_correct_data + ml_wrong_data
    ann_eval = ml_correct_ann + ml_wrong_ann
    data_acc = ml_correct_data / data_eval * 100 if data_eval else 0
    ann_acc = ml_correct_ann / ann_eval * 100 if ann_eval else 0

    print(f"\n{'='*60}")
    print("ML (CatBoost train→eval) ACCURACY")
    print(f"{'='*60}")
    print(f"  Overall:    {ml_correct}/{ml_evaluated} ({ml_acc:.1f}%)")
    print(f"  Data cols:  {ml_correct_data}/{data_eval} ({data_acc:.1f}%)")
    print(f"  Ann cols:   {ml_correct_ann}/{ann_eval} ({ann_acc:.1f}%)")
    print(f"{'='*60}")

    # Print misclassified columns for error analysis
    if misclassified:
        print(f"\n  Misclassified columns ({len(misclassified)}):")
        for m in sorted(misclassified, key=lambda x: x["kind"]):
            print(f"    [{m['kind'][:3]}] {m['column']}: "
                  f"expected {m['expected']}, "
                  f"got {m['predicted']} (conf={m['confidence']})")

    accuracy_metrics = {
        "total_evaluated": ml_evaluated,
        "correct": ml_correct,
        "wrong": ml_wrong,
        "accuracy": round(ml_acc / 100, 4),
        "data_accuracy": round(data_acc / 100, 4),
        "annotation_accuracy": round(ann_acc / 100, 4),
    }

    return ml_preds, accuracy_metrics


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
        ("belief", pa.float64()),
        ("plausibility", pa.float64()),
        ("uncertainty_gap", pa.float64()),
        ("conflict", pa.float64()),
        ("needs_clarification", pa.bool_()),
        ("evidence_sources", pa.string()),
        ("belief_path", pa.string()),
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


def _write_report_json(
    output: Path,
    args,
    accuracy_metrics: dict | None,
    ml_accuracy_metrics: dict | None,
    sage_dict: dict | None,
    enabled_features: list[str],
    n_records: int,
    gt_source: str | None,
    results: list[dict] | None = None,
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

    # Uncertainty summary
    if results:
        gaps = [r["uncertainty_gap"] for r in results if r.get("belief", 0) > 0]
        conflicts = [r["conflict"] for r in results if r.get("belief", 0) > 0]
        clarification_count = sum(1 for r in results if r.get("needs_clarification", False))
        report["uncertainty_summary"] = {
            "avg_uncertainty_gap": round(sum(gaps) / len(gaps), 4) if gaps else 0.0,
            "avg_conflict": round(sum(conflicts) / len(conflicts), 4) if conflicts else 0.0,
            "clarification_count": clarification_count,
            "columns_evaluated": len(gaps),
        }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  {report_path.name}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build SAGE-enhanced classified parquet for embedding-atlas",
    )
    # None defaults = fall through to HOCON config (config/base.conf)
    p.add_argument("--data-dir", required=True, help="Path to data directory")
    p.add_argument("--output", default=None, help="Output parquet file path (from config)")
    p.add_argument(
        "--taxonomy",
        choices=["sigdg", "annotations"],
        default=None,
        help="Taxonomy to classify against (from config)",
    )
    p.add_argument(
        "--embedding-model", default=None,
        help="SentenceTransformer model (from config)",
    )
    p.add_argument("--model-path", default=None, help="Path to trained CatBoost model (.cbm)")
    p.add_argument(
        "--threshold", type=float, default=None,
        help="Minimum confidence threshold (from config)",
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
        "--sage-permutations", type=int, default=None,
        help="SAGE permutation count (from config)",
    )
    p.add_argument(
        "--ground-truth", default=None,
        help="Path to LLM ground truth JSON (column→code mappings)",
    )
    p.add_argument(
        "--ml-folds", type=int, default=None,
        help="Number of CatBoost CV folds (from config)",
    )
    p.add_argument(
        "--train-dir", default=None,
        help="Path to synthetic training data directory. "
        "When provided, trains CatBoost on synthetic data and evaluates on real data "
        "instead of running k-fold CV.",
    )
    p.add_argument(
        "--no-concat-features",
        action="store_true",
        help="Disable discrete feature concatenation (ablation: embedding-only CatBoost).",
    )
    p.add_argument(
        "--input-format",
        choices=["csv", "parquet"],
        default=None,
        help="Input data format (from config)",
    )
    p.add_argument(
        "--taxonomy-file", default=None,
        help="Path to custom taxonomy Python module",
    )
    args = p.parse_args(argv)

    # ── Load config (HOCON + env vars), then overlay CLI args ────────
    from sigint.config import load_config

    overrides: dict = {"data_dir": args.data_dir}
    if args.output is not None:
        overrides["output"] = args.output
    if args.taxonomy is not None:
        overrides["taxonomy_name"] = args.taxonomy
    if args.embedding_model is not None:
        overrides["embedding_model"] = args.embedding_model
    if args.model_path is not None:
        overrides["model_path"] = args.model_path
    if args.threshold is not None:
        overrides["confidence_threshold"] = args.threshold
    if args.no_name_boost:
        overrides["name_match_boost"] = False
    if args.sage_permutations is not None:
        overrides["sage_permutations"] = args.sage_permutations
    if args.ground_truth is not None:
        overrides["ground_truth"] = args.ground_truth
    if args.ml_folds is not None:
        overrides["ml_folds"] = args.ml_folds
    if args.train_dir is not None:
        overrides["train_dir"] = args.train_dir
    if args.input_format is not None:
        overrides["input_format"] = args.input_format
    if args.taxonomy_file is not None:
        overrides["taxonomy_file"] = args.taxonomy_file
    if args.no_concat_features:
        overrides["concat_features"] = False

    cfg = load_config(overrides=overrides)

    # Backfill args from resolved config so downstream code works unchanged
    args.taxonomy = cfg.taxonomy_name
    args.embedding_model = cfg.embedding_model
    args.threshold = cfg.confidence_threshold
    args.sage_permutations = cfg.sage_permutations
    args.ml_folds = cfg.ml_folds
    args.output = cfg.output
    args.input_format = cfg.input_format
    if args.ground_truth is None and cfg.ground_truth:
        args.ground_truth = cfg.ground_truth
    if args.train_dir is None and cfg.train_dir:
        args.train_dir = cfg.train_dir

    data_dir = Path(args.data_dir).expanduser()
    output = Path(args.output)

    if not data_dir.is_dir():
        print(f"Error: {data_dir} is not a directory", file=sys.stderr)
        return 1

    # ── Build category set ───────────────────────────────────────────
    # For annotations taxonomy, auto-detect CSV path from data-dir if not configured
    if cfg.taxonomy_name == "annotations" and not cfg.annotations_path:
        ann_path = data_dir / "annotations.csv"
        if ann_path.exists():
            cfg = load_config(overrides={**overrides, "annotations_path": str(ann_path)})

    try:
        category_set = cfg.build_category_set(hierarchical=True)
        print(f"Loaded {cfg.taxonomy_name} taxonomy: {len(category_set.categories)} leaf categories")
    except ValueError:
        category_set = None

    # ── Feature mask ─────────────────────────────────────────────────
    feature_mask = build_feature_mask(args.disable_features)
    enabled_features = list(FEATURE_NAMES)
    if feature_mask:
        enabled_features = [n for n, v in feature_mask.items() if v]
        disabled = [n for n, v in feature_mask.items() if not v]
        print(f"Feature mask: {len(enabled_features)}/{len(FEATURE_NAMES)} features enabled")
        print(f"  Disabled: {disabled}")

    # ── Stage 1: Load + Feature Extraction ───────────────────────────
    print(f"Loading columns from {data_dir} ({args.input_format} format)...")
    if args.input_format == "parquet":
        # For parquet, data_dir should point to the parquet file directly,
        # or we look for *.parquet in the directory
        data_path = Path(data_dir)
        if data_path.is_file() and data_path.suffix == ".parquet":
            records = load_parquet_columns(data_path)
        else:
            pq_files = sorted(data_path.glob("*_columns.parquet"))
            if not pq_files:
                pq_files = sorted(data_path.glob("*.parquet"))
            if not pq_files:
                print(f"Error: no parquet files found in {data_dir}", file=sys.stderr)
                return 1
            records = load_parquet_columns(pq_files[0])
            print(f"  Using {pq_files[0].name}")
    else:
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

        # Extract belief interval from HierarchicalClassification
        bel = 0.0
        pl = 0.0
        if classification is not None:
            bel = classification.belief_at(classification.category.code)
            pl = classification.plausibility_at(classification.category.code)

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
            "belief": round(bel, 4),
            "plausibility": round(pl, 4),
            "uncertainty_gap": round(pl - bel, 4),
            "conflict": classification.conflict if classification else 0.0,
            "needs_clarification": classification.needs_clarification if classification else False,
        }

        # Source evidence summary as JSON
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

        # Belief path from leaf to root
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
        bel_info = ""
        if row["belief"] > 0:
            bel_info = f" [Bel={row['belief']:.2f}, Pl={row['plausibility']:.2f}]"
        print(f"  [{i}/{total}] {rec['source_table']}.{rec['column_name']} -> {tag} ({conf:.2f}){bel_info}")

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

    # ── Stage 3.5: CatBoost predictions ─────────────────────────────
    ml_accuracy_metrics: dict | None = None

    if args.train_dir and gt and category_set:
        # ── Train/eval split using synthetic training data ─────────
        train_dir = Path(args.train_dir).expanduser()
        print(f"\nLoading synthetic training data from {train_dir}...")
        train_records = load_csv_columns(train_dir)
        train_gt = _load_ground_truth(train_dir / "ground_truth.json")
        print(f"  Synthetic columns: {len(train_records)}, GT mappings: {len(train_gt)}")

        concat = not args.no_concat_features
        print(f"  Feature concatenation: {'enabled' if concat else 'disabled'}")

        ml_preds, ml_accuracy_metrics = _run_catboost_train_eval(
            clf,
            train_records=train_records,
            train_gt=train_gt,
            eval_records=records,
            eval_results=results,
            eval_features_list=all_features,
            eval_gt=gt,
            category_set=category_set,
            concat_features=concat,
        )

        for row, ml in zip(results, ml_preds):
            row["ml_tag_code"] = ml["ml_tag_code"]
            row["ml_tag_label"] = ml["ml_tag_label"]
            row["ml_confidence"] = ml["ml_confidence"]

        for row, rec in zip(results, records):
            col = rec["column_name"]
            if col in gt:
                row["ml_correct"] = "correct" if row["ml_tag_code"] == gt[col] else "wrong"

    elif gt and category_set:
        # ── Fallback: k-fold CV on real data ───────────────────────
        print(f"\nRunning CatBoost {args.ml_folds}-fold CV...")
        ml_preds = _run_catboost_cv(
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
        print("ML (CatBoost CV) ACCURACY")
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
        enabled_features, len(results), gt_source, results=results,
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
