"""Item-wise SHAP feature importance analysis.

Provides per-item (per-column) explanations of classification decisions,
complementing the global SAGE analysis.  Two methods are available:

1. **CatBoost TreeSHAP** — exact O(TLD) algorithm on the 991-dim CatBoost
   feature space.  Fast (~2 seconds for 350 items), but features are raw
   dimensions (embeddings, cosine sims, discrete features).  We group
   these back to interpretable feature groups before selecting top-k.

2. **Embedding PermutationSHAP** — ``shap.PermutationExplainer`` on the
   12-feature embedding classifier (column_name, sample_values, etc.).
   More interpretable but slower; benefits from GPU encoding.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np


# ── Feature group definitions for CatBoost 991-dim space ────────────
#
# CatBoost features are: [full_emb(384) | vo_emb(384) | discrete(11) | cosine(N_ref)]
# We group SHAP values back to interpretable names.

_DISCRETE_NAMES = [
    "cardinality",
    "null_ratio",
    "value_entropy",
    "pattern_email",
    "pattern_phone",
    "pattern_ssn",
    "pattern_ipv4",
    "pattern_uuid",
    "pattern_date_iso",
    "pattern_url",
    "pattern_credit_card",
]


def _build_feature_groups(emb_dim: int, n_discrete: int, n_cosine: int) -> list[tuple[str, int, int]]:
    """Build (name, start, end) slices mapping CatBoost dims to groups.

    Returns list of (group_name, start_idx, end_idx) tuples where
    end_idx is exclusive.
    """
    groups: list[tuple[str, int, int]] = []
    offset = 0

    # Full embedding
    groups.append(("full_embedding", offset, offset + emb_dim))
    offset += emb_dim

    # Value-only embedding
    groups.append(("value_only_embedding", offset, offset + emb_dim))
    offset += emb_dim

    # Discrete features (11 individual features)
    for i, name in enumerate(_DISCRETE_NAMES[:n_discrete]):
        groups.append((name, offset + i, offset + i + 1))
    offset += n_discrete

    # Cosine similarities (grouped as one)
    if n_cosine > 0:
        groups.append(("cosine_similarities", offset, offset + n_cosine))
        offset += n_cosine

    return groups


@dataclass(frozen=True)
class ShapResult:
    """Result of item-wise SHAP analysis."""

    feature_names: list[str]
    shap_values: np.ndarray  # (N, n_groups) — per-item grouped scores
    base_value: float
    method: str  # "catboost_treeshap" or "embedding_permutation"
    n_items: int
    elapsed_seconds: float

    def top_features(self, item_idx: int, k: int = 3) -> list[tuple[str, float]]:
        """Top-k features by absolute SHAP value for one item."""
        vals = self.shap_values[item_idx]
        indices = np.argsort(-np.abs(vals))[:k]
        return [(self.feature_names[i], float(vals[i])) for i in indices]

    def to_records(self, k: int = 3) -> list[dict]:
        """Per-item dicts with shap_top1_name, shap_top1_value, ..., shap_topK_*."""
        records = []
        for i in range(self.n_items):
            row: dict = {}
            top = self.top_features(i, k=k)
            for rank, (name, value) in enumerate(top, 1):
                row[f"shap_top{rank}_name"] = name
                row[f"shap_top{rank}_value"] = round(value, 6)
            # Pad if fewer than k features
            for rank in range(len(top) + 1, k + 1):
                row[f"shap_top{rank}_name"] = ""
                row[f"shap_top{rank}_value"] = 0.0
            records.append(row)
        return records


def run_catboost_shap(
    model,
    X_eval: np.ndarray,
    predicted_indices: np.ndarray,
    emb_dim: int = 384,
    n_discrete: int = 11,
) -> ShapResult:
    """Compute item-wise SHAP values using CatBoost's built-in TreeSHAP.

    Args:
        model: Fitted CatBoostClassifier.
        X_eval: (N, n_features) scaled feature matrix used for prediction.
        predicted_indices: (N,) array of predicted class indices.
        emb_dim: Embedding dimension (default 384 for MiniLM-L6).
        n_discrete: Number of discrete features (default 11).

    Returns:
        ShapResult with grouped feature importance per item.
    """
    from catboost import Pool

    t0 = time.time()
    N, total_dim = X_eval.shape

    pool = Pool(X_eval)

    # CatBoost ShapValues: (N, n_features+1, n_classes) for MultiClass
    # Last feature dim is the base value.
    raw_shap = model.get_feature_importance(
        type="ShapValues",
        data=pool,
    )

    n_feat = total_dim

    # CatBoost ShapValues shape:
    #   MultiClass: (N, n_classes, n_features+1)
    #   Binary:     (N, n_features+1)
    if raw_shap.ndim == 3:
        # Extract SHAP values for each item's predicted class
        item_shap = np.zeros((N, n_feat))
        base_values = np.zeros(N)
        for i in range(N):
            cls_idx = int(predicted_indices[i])
            item_shap[i] = raw_shap[i, cls_idx, :n_feat]
            base_values[i] = raw_shap[i, cls_idx, n_feat]
        base_value = float(np.mean(base_values))
    else:
        # Binary classification
        item_shap = raw_shap[:, :n_feat]
        base_value = float(np.mean(raw_shap[:, n_feat]))

    # Group raw dims into interpretable feature groups
    n_cosine = total_dim - (emb_dim * 2 + n_discrete)
    if n_cosine < 0:
        n_cosine = 0
    groups = _build_feature_groups(emb_dim, n_discrete, n_cosine)

    group_names = [g[0] for g in groups]
    grouped_shap = np.zeros((N, len(groups)))

    for g_idx, (_, start, end) in enumerate(groups):
        if end <= n_feat:
            grouped_shap[:, g_idx] = np.sum(item_shap[:, start:end], axis=1)

    elapsed = time.time() - t0

    print(f"  CatBoost TreeSHAP: {N} items, {len(groups)} feature groups, {elapsed:.1f}s")

    return ShapResult(
        feature_names=group_names,
        shap_values=grouped_shap,
        base_value=base_value,
        method="catboost_treeshap",
        n_items=N,
        elapsed_seconds=elapsed,
    )


def run_embedding_shap(
    all_features,
    classifier,
    category_set,
    ground_truth_indices: np.ndarray,
    feature_mask: dict[str, bool] | None = None,
) -> ShapResult:
    """Compute item-wise SHAP values on the 12-feature embedding classifier.

    Uses ``shap.PermutationExplainer`` which is model-agnostic but benefits
    from GPU-accelerated sentence-transformer encoding.

    Args:
        all_features: List of ColumnFeatures for evaluated items.
        classifier: EmbeddingClassifier instance.
        category_set: CategorySet with category definitions.
        ground_truth_indices: (N,) array of class indices for evaluation.
        feature_mask: Base feature mask (disabled features excluded).

    Returns:
        ShapResult with per-item SHAP values on the 12 named features.
    """
    import shap

    from sigint.features import FEATURE_NAMES
    from sigint.sage_analysis import FeatureMaskModel

    t0 = time.time()
    N = len(all_features)
    n_feat = len(FEATURE_NAMES)

    # Build feature index matrix (same as SAGE)
    X = np.tile(np.arange(N).reshape(-1, 1), (1, n_feat))

    # Wrap classifier
    model_fn = FeatureMaskModel(
        all_features, classifier, category_set, feature_mask
    )

    explainer = shap.PermutationExplainer(model_fn, X)
    shap_values = explainer(X)

    # shap_values.values: (N, n_feat, n_classes)
    # Extract values for predicted class per item
    raw = shap_values.values
    if raw.ndim == 3:
        item_shap = np.zeros((N, n_feat))
        for i in range(N):
            cls_idx = int(ground_truth_indices[i])
            item_shap[i] = raw[i, :, cls_idx]
    else:
        item_shap = raw

    base_value = float(np.mean(shap_values.base_values))

    elapsed = time.time() - t0

    # Report cache performance
    total_lookups = model_fn.cache_hits + model_fn.cache_misses
    if total_lookups > 0:
        hit_rate = model_fn.cache_hits / total_lookups * 100
        print(f"  Embedding SHAP cache: {model_fn.cache_hits}/{total_lookups} hits "
              f"({hit_rate:.0f}%), {model_fn.cache_misses} encodes")

    print(f"  Embedding PermutationSHAP: {N} items, {n_feat} features, {elapsed:.1f}s")

    return ShapResult(
        feature_names=list(FEATURE_NAMES),
        shap_values=item_shap,
        base_value=base_value,
        method="embedding_permutation",
        n_items=N,
        elapsed_seconds=elapsed,
    )
