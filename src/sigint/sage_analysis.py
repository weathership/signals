"""SAGE (Shapley Additive Global importancE) feature importance analysis.

Wraps the sage-importance library to measure the global importance of each
feature in the ColumnFeatures set.  When SAGE marginalizes a feature, it
substitutes values from other samples — e.g., "what if this column had a
different name but the same values?".
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from sigint.features import FEATURE_NAMES, ColumnFeatures


@dataclass(frozen=True)
class SageResult:
    """Result of a SAGE feature importance analysis."""

    feature_names: list[str]
    importance_values: list[float]
    importance_std: list[float]
    method: str
    loss_function: str
    n_samples: int
    elapsed_seconds: float

    def to_dict(self) -> dict:
        return {
            "feature_names": self.feature_names,
            "importance_values": self.importance_values,
            "importance_std": self.importance_std,
            "method": self.method,
            "loss_function": self.loss_function,
            "n_samples": self.n_samples,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


class FeatureMaskModel:
    """Wraps a classifier as a model function for SAGE.

    SAGE requires ``model(X) -> predictions`` where X is (N, D).
    Our X has shape (N, 11) where X[i, j] = index into per-feature value
    lookup table.  When SAGE marginalizes feature j for sample i, it
    substitutes sample k's value — asking "what if this column had a
    different name but the same values?".

    The model looks up actual text from per-feature tables, builds embedding
    text, encodes, and returns softmax'd cosine similarities.

    An LRU embedding cache avoids re-encoding identical texts across SAGE
    permutations — many marginalizations produce duplicate feature
    combinations.
    """

    def __init__(
        self,
        all_features: list[ColumnFeatures],
        classifier,
        category_set,
        feature_mask: dict[str, bool] | None = None,
        cache_size: int = 4096,
    ):
        self.all_features = all_features
        self.classifier = classifier
        self.category_set = category_set
        self.base_mask = feature_mask
        self.n_features = len(FEATURE_NAMES)
        self.n_classes = len(category_set.categories)

        # Build per-feature value lookup tables.
        # feature_values[j] = list of feature-text values for all samples
        self.feature_values: list[list[str]] = []
        for fname in FEATURE_NAMES:
            vals = []
            for feat in all_features:
                vals.append(feat.feature_value(fname))
            self.feature_values.append(vals)

        # Embedding cache: text → normalized embedding vector
        self._cache: dict[str, np.ndarray] = {}
        self._cache_size = cache_size
        self.cache_hits = 0
        self.cache_misses = 0

    def __call__(self, X: np.ndarray) -> np.ndarray:
        """Predict class probabilities for a batch of feature index vectors.

        Args:
            X: (N, 11) array of sample indices per feature.

        Returns:
            (N, n_classes) array of softmax'd cosine similarities.
        """
        N = X.shape[0]
        model = self.classifier._get_model()
        cat_embs = self.classifier._get_category_embeddings()
        dim = cat_embs.shape[1]

        # Build embedding texts by mixing feature values according to X
        texts: list[str] = []
        for i in range(N):
            parts = []
            for j, fname in enumerate(FEATURE_NAMES):
                if self.base_mask and not self.base_mask.get(fname, True):
                    continue
                idx = int(X[i, j])
                val = self.feature_values[j][idx]
                if val:
                    parts.append(val)
            texts.append(" | ".join(parts) if parts else "")

        if not texts:
            return np.zeros((N, self.n_classes))

        # Split into cached hits, within-batch dedup hits, and true misses.
        # pending maps unique uncached text → list of row indices needing it.
        vecs = np.zeros((N, dim))
        pending: dict[str, list[int]] = {}

        for i, text in enumerate(texts):
            cached = self._cache.get(text)
            if cached is not None:
                vecs[i] = cached
                self.cache_hits += 1
            elif text in pending:
                pending[text].append(i)
                self.cache_hits += 1  # within-batch dedup
            else:
                pending[text] = [i]
                self.cache_misses += 1

        # Batch encode only unique uncached texts
        if pending:
            unique_texts = list(pending.keys())
            batch_size = self.classifier._config.batch_size
            raw = model.encode(unique_texts, batch_size=batch_size,
                               show_progress_bar=False)
            norms = np.linalg.norm(raw, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            normed = raw / norms

            for j, text in enumerate(unique_texts):
                vec = normed[j]
                for idx in pending[text]:
                    vecs[idx] = vec
                if len(self._cache) < self._cache_size:
                    self._cache[text] = vec

        # Cosine similarities
        sims = vecs @ cat_embs.T  # (N, n_classes)

        # Softmax to produce probabilities
        exp_sims = np.exp(sims - np.max(sims, axis=1, keepdims=True))
        probs = exp_sims / np.sum(exp_sims, axis=1, keepdims=True)

        return probs


def run_sage_analysis(
    all_features: list[ColumnFeatures],
    ground_truth_indices: np.ndarray,
    classifier,
    category_set,
    method_name: str = "cosine",
    loss: str = "cross entropy",
    feature_mask: dict[str, bool] | None = None,
    n_permutations: int = 512,
    detect_convergence: bool = True,
) -> SageResult:
    """Run SAGE feature importance analysis.

    Args:
        all_features: List of ColumnFeatures for evaluated samples.
        ground_truth_indices: (N,) array of ground truth class indices.
        classifier: EmbeddingClassifier instance.
        category_set: CategorySet with category definitions.
        method_name: Name of the classification method.
        loss: Loss function for SAGE (default: "cross entropy").
        feature_mask: Base feature mask (disabled features excluded from analysis).
        n_permutations: Number of SAGE permutations.
        detect_convergence: Stop early when importance values stabilize
            (default: True).

    Returns:
        SageResult with per-feature importance values.
    """
    import sage

    t0 = time.time()
    N = len(all_features)
    n_feat = len(FEATURE_NAMES)

    # Build feature index matrix: X[i, j] = i (each sample uses its own values)
    X = np.tile(np.arange(N).reshape(-1, 1), (1, n_feat))

    # Ground truth as integer class indices (shape (N,)) for cross entropy loss
    Y = ground_truth_indices.astype(int)

    # Wrap classifier as SAGE-compatible model
    model_fn = FeatureMaskModel(
        all_features, classifier, category_set, feature_mask
    )

    # MarginalImputer: marginalizes features by substituting from data distribution
    imputer = sage.MarginalImputer(model_fn, X)

    # Permutation estimator for SAGE values
    estimator = sage.PermutationEstimator(imputer, loss=loss)
    explanation = estimator(
        X, Y,
        n_permutations=n_permutations,
        detect_convergence=detect_convergence,
        bar=False,
    )

    elapsed = time.time() - t0

    # Report cache performance
    total_lookups = model_fn.cache_hits + model_fn.cache_misses
    if total_lookups > 0:
        hit_rate = model_fn.cache_hits / total_lookups * 100
        print(f"  Embedding cache: {model_fn.cache_hits}/{total_lookups} hits "
              f"({hit_rate:.0f}%), {model_fn.cache_misses} encodes")

    return SageResult(
        feature_names=list(FEATURE_NAMES),
        importance_values=[round(float(v), 6) for v in explanation.values],
        importance_std=[round(float(s), 6) for s in explanation.std],
        method=method_name,
        loss_function=loss,
        n_samples=N,
        elapsed_seconds=elapsed,
    )
