#!/usr/bin/env python3
"""Train an XGBoost classifier on LLM-labeled embedding data.

Reads a labeled parquet (from build_sigint_embeddings.py with --classifier llm),
embeds each column's embedding_text, and trains an XGBClassifier.

Usage:
    # Step 1: generate LLM-labeled training data
    uv run python scripts/build_sigint_embeddings.py \
        --data-dir ~/local/tmp/meta-tagging/ --classifier llm \
        --api-key $ANTHROPIC_API_KEY --output build/sigint_llm_labeled.parquet

    # Step 2: train XGBoost on it
    uv run python scripts/train_xgboost.py \
        --input build/sigint_llm_labeled.parquet \
        --output build/sigint_xgb_model.json \
        --embedding-model all-MiniLM-L6-v2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Train XGBoost on LLM-labeled embeddings",
    )
    p.add_argument(
        "--input",
        required=True,
        help="Input parquet with sigdg_label and embedding_text columns",
    )
    p.add_argument(
        "--output",
        default="build/sigint_xgb_model.json",
        help="Output model file path (.json)",
    )
    p.add_argument(
        "--embedding-model",
        default="all-MiniLM-L6-v2",
        help="SentenceTransformer model (default: all-MiniLM-L6-v2)",
    )
    p.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Fraction of data held out for evaluation (default: 0.2)",
    )

    args = p.parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        return 1

    # Lazy imports — these are heavy
    import numpy as np
    import pyarrow.parquet as pq
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder
    from xgboost import XGBClassifier

    # Load labeled data
    print(f"Loading {input_path}...")
    table = pq.read_table(input_path)
    texts = table.column("embedding_text").to_pylist()
    labels = table.column("sigdg_label").to_pylist()
    codes = table.column("sigdg_code").to_pylist()

    # Filter out unclassified
    filtered = [
        (t, l, c) for t, l, c in zip(texts, labels, codes)
        if l != "unclassified" and c
    ]

    if len(filtered) < 5:
        print(f"Error: only {len(filtered)} labeled samples — need at least 5", file=sys.stderr)
        return 1

    texts_f, labels_f, codes_f = zip(*filtered)
    texts_f = list(texts_f)
    labels_f = list(labels_f)
    codes_f = list(codes_f)

    print(f"Labeled samples: {len(texts_f)} (filtered from {len(texts)})")
    print(f"Unique labels: {len(set(labels_f))}")

    # Encode texts → embeddings
    print(f"Encoding with {args.embedding_model}...")
    model = SentenceTransformer(args.embedding_model)
    X = model.encode(texts_f, batch_size=32, show_progress_bar=True)

    # Encode labels
    le = LabelEncoder()
    y = le.fit_transform(codes_f)
    class_codes = le.classes_.tolist()

    print(f"Embedding shape: {X.shape}")
    print(f"Classes: {len(class_codes)}")

    # Train/test split
    if len(set(y)) > 1 and len(texts_f) >= 10:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=args.test_size, random_state=42, stratify=y
        )
    else:
        # Too few samples for stratified split — use all for training
        X_train, y_train = X, y
        X_test, y_test = X, y
        print("Warning: too few samples for proper train/test split, using full dataset")

    # Train XGBoost
    print("Training XGBoost...")
    xgb = XGBClassifier(
        objective="multi:softprob",
        num_class=len(class_codes),
        max_depth=6,
        n_estimators=100,
        reg_alpha=0.5,
        learning_rate=0.1,
        eval_metric="mlogloss",
        random_state=42,
    )
    xgb.fit(X_train, y_train)

    # Evaluate
    y_pred = xgb.predict(X_test)
    target_names = [f"{c} ({le.inverse_transform([i])[0]})" for i, c in enumerate(class_codes)]

    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=target_names, zero_division=0))

    # Save model
    output_path.parent.mkdir(parents=True, exist_ok=True)
    xgb.save_model(str(output_path))

    # Save class mapping alongside model
    classes_path = output_path.with_suffix(".classes.json")
    classes_path.write_text(json.dumps(class_codes, indent=2))

    print(f"Saved model to {output_path}")
    print(f"Saved class mapping to {classes_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
