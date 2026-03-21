"""Tests for the SAGE feature importance analysis module."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from sigint.category_set import CategorySet, ReferenceCategory
from sigint.features import FEATURE_NAMES, ColumnFeatures
from sigint.sage_analysis import FeatureMaskModel, SageResult


def _make_features(name: str = "email", table: str = "users") -> ColumnFeatures:
    return ColumnFeatures(
        column_name_humanized=name,
        column_type=None,
        sample_values_text="a@b.com, c@d.org",
        cardinality=2,
        null_ratio=0.0,
        value_entropy=1.0,
        pattern_signals=["email_pattern"],
        avg_value_length=10.0,
        numeric_ratio=0.0,
        sibling_names=["first name"],
        source_table=table,
    )


def _make_category_set() -> CategorySet:
    return CategorySet(
        name="test",
        categories=[
            ReferenceCategory(
                code="A", label="Email", embedding_text="email address",
                abbrev="EMAIL", taxonomy="test",
            ),
            ReferenceCategory(
                code="B", label="Phone", embedding_text="phone number",
                abbrev="PHONE", taxonomy="test",
            ),
        ],
    )


def _make_mock_classifier(dim=384, n_cats=2):
    """Create a mock classifier with deterministic embeddings."""
    clf = MagicMock()
    clf._config = MagicMock()
    clf._config.batch_size = 32

    mock_model = MagicMock()
    cat_embs = np.eye(n_cats, dim)

    def mock_encode(texts, batch_size=32, **kwargs):
        n = len(texts)
        vecs = np.zeros((n, dim))
        for i in range(n):
            # Simple heuristic: email-like texts point to cat 0, others to cat 1
            if "email" in texts[i].lower():
                vecs[i, 0] = 1.0
            else:
                vecs[i, 1] = 1.0
        return vecs

    mock_model.encode = mock_encode
    clf._get_model.return_value = mock_model
    clf._get_category_embeddings.return_value = cat_embs
    return clf


# ── SageResult ───────────────────────────────────────────────────────


class TestSageResult:
    def test_to_dict(self):
        result = SageResult(
            feature_names=["col_name", "col_type"],
            importance_values=[0.42, 0.08],
            importance_std=[0.01, 0.005],
            method="cosine",
            loss_function="cross entropy",
            n_samples=100,
            elapsed_seconds=12.345,
        )
        d = result.to_dict()
        assert d["feature_names"] == ["col_name", "col_type"]
        assert d["importance_values"] == [0.42, 0.08]
        assert d["importance_std"] == [0.01, 0.005]
        assert d["method"] == "cosine"
        assert d["n_samples"] == 100
        assert d["elapsed_seconds"] == 12.35

    def test_frozen(self):
        result = SageResult(
            feature_names=[], importance_values=[], importance_std=[],
            method="x", loss_function="y", n_samples=0, elapsed_seconds=0,
        )
        try:
            result.method = "z"  # type: ignore[misc]
            assert False, "Should be frozen"
        except AttributeError:
            pass


# ── FeatureMaskModel ─────────────────────────────────────────────────


class TestFeatureMaskModel:
    def test_call_returns_probabilities(self):
        features = [_make_features("email"), _make_features("phone")]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        model = FeatureMaskModel(features, clf, cs)
        # X[i, j] = i → each sample uses its own features
        X = np.array([[0] * 11, [1] * 11])
        probs = model(X)

        assert probs.shape == (2, 2)
        # Probabilities should sum to 1
        np.testing.assert_allclose(probs.sum(axis=1), [1.0, 1.0], atol=1e-6)

    def test_probabilities_positive(self):
        features = [_make_features("email")]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        model = FeatureMaskModel(features, clf, cs)
        X = np.array([[0] * 11])
        probs = model(X)
        assert (probs >= 0).all()

    def test_feature_mask_excludes_features(self):
        features = [_make_features("email")]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        mask = {n: False for n in FEATURE_NAMES}
        mask["column_name"] = True  # only column name enabled

        model = FeatureMaskModel(features, clf, cs, feature_mask=mask)
        X = np.array([[0] * 11])
        probs = model(X)
        assert probs.shape == (1, 2)
        assert probs.sum() > 0

    def test_feature_values_populated(self):
        features = [
            _make_features("email", "users"),
            _make_features("phone", "contacts"),
        ]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        model = FeatureMaskModel(features, clf, cs)
        # column_name is index 0 in FEATURE_NAMES
        assert len(model.feature_values) == 11
        # First feature (column_name): values for 2 samples
        assert len(model.feature_values[0]) == 2


# ── Integration with mocked SAGE ─────────────────────────────────────


class TestEmbeddingCache:
    def test_cache_hits_on_duplicate_texts(self):
        """Duplicate texts should produce cache hits."""
        features = [_make_features("email"), _make_features("email")]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        model = FeatureMaskModel(features, clf, cs)
        X = np.array([[0] * 11, [0] * 11])  # same indices → same text
        model(X)

        # First call: both texts identical, but first is a miss, second is a hit
        assert model.cache_hits == 1
        assert model.cache_misses == 1

    def test_cache_miss_on_different_texts(self):
        """Different texts should produce cache misses."""
        features = [_make_features("email"), _make_features("phone")]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        model = FeatureMaskModel(features, clf, cs)
        X = np.array([[0] * 11, [1] * 11])  # different indices → different text
        model(X)

        assert model.cache_hits == 0
        assert model.cache_misses == 2

    def test_cache_reused_across_calls(self):
        """Cache should be reused across multiple __call__ invocations."""
        features = [_make_features("email"), _make_features("phone")]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        model = FeatureMaskModel(features, clf, cs)
        X0 = np.array([[0] * 11])
        X1 = np.array([[0] * 11])  # same text as X0

        model(X0)
        assert model.cache_misses == 1
        assert model.cache_hits == 0

        model(X1)
        assert model.cache_misses == 1  # no new misses
        assert model.cache_hits == 1

    def test_cache_size_limit(self):
        """Cache should stop storing after reaching cache_size."""
        features = [_make_features(f"col_{i}") for i in range(5)]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        model = FeatureMaskModel(features, clf, cs, cache_size=2)
        X = np.array([[i] * 11 for i in range(5)])
        model(X)

        assert len(model._cache) == 2  # only 2 entries stored


class TestRunSageAnalysis:
    def test_produces_sage_result(self):
        """Test run_sage_analysis with real SAGE library but mock classifier."""
        from sigint.sage_analysis import run_sage_analysis

        features = [
            _make_features("email"),
            _make_features("phone"),
            _make_features("email"),
        ]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)

        gt_indices = np.array([0, 1, 0])  # email=A, phone=B, email=A

        result = run_sage_analysis(
            all_features=features,
            ground_truth_indices=gt_indices,
            classifier=clf,
            category_set=cs,
            method_name="cosine",
            n_permutations=4,  # minimal for speed
        )

        assert isinstance(result, SageResult)
        assert len(result.feature_names) == 11
        assert len(result.importance_values) == 11
        assert len(result.importance_std) == 11
        assert result.method == "cosine"
        assert result.n_samples == 3
        assert result.elapsed_seconds > 0

    def test_convergence_detection_flag(self):
        """Test that detect_convergence parameter is accepted."""
        from sigint.sage_analysis import run_sage_analysis

        features = [_make_features("email"), _make_features("phone")]
        cs = _make_category_set()
        clf = _make_mock_classifier(n_cats=2)
        gt_indices = np.array([0, 1])

        # Should not raise — convergence detection enabled
        result = run_sage_analysis(
            all_features=features,
            ground_truth_indices=gt_indices,
            classifier=clf,
            category_set=cs,
            n_permutations=4,
            detect_convergence=True,
        )
        assert isinstance(result, SageResult)
