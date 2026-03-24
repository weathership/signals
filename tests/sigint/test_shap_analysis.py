"""Tests for the SHAP item-wise feature importance module."""

from __future__ import annotations

import numpy as np
import pytest

from sigint.shap_analysis import (
    ShapResult,
    _build_feature_groups,
    run_catboost_shap,
)


# ── ShapResult ───────────────────────────────────────────────────────


class TestShapResult:
    def test_top_features_returns_sorted_by_abs_value(self):
        vals = np.array([
            [0.1, -0.5, 0.3, 0.0],
            [0.4, 0.2, -0.1, 0.0],
        ])
        result = ShapResult(
            feature_names=["a", "b", "c", "d"],
            shap_values=vals,
            base_value=0.0,
            method="test",
            n_items=2,
            elapsed_seconds=0.1,
        )

        top = result.top_features(0, k=3)
        assert len(top) == 3
        # Sorted by abs value: b(-0.5), c(0.3), a(0.1)
        assert top[0][0] == "b"
        assert top[1][0] == "c"
        assert top[2][0] == "a"

    def test_top_features_preserves_sign(self):
        vals = np.array([[-0.5, 0.3]])
        result = ShapResult(
            feature_names=["a", "b"],
            shap_values=vals,
            base_value=0.0,
            method="test",
            n_items=1,
            elapsed_seconds=0.1,
        )
        top = result.top_features(0, k=2)
        assert top[0] == ("a", -0.5)
        assert top[1] == ("b", 0.3)

    def test_to_records_produces_top3(self):
        vals = np.array([[0.1, -0.5, 0.3, 0.0]])
        result = ShapResult(
            feature_names=["a", "b", "c", "d"],
            shap_values=vals,
            base_value=0.0,
            method="test",
            n_items=1,
            elapsed_seconds=0.1,
        )
        records = result.to_records(k=3)
        assert len(records) == 1
        row = records[0]
        assert row["shap_top1_name"] == "b"
        assert row["shap_top1_value"] == pytest.approx(-0.5, abs=1e-5)
        assert row["shap_top2_name"] == "c"
        assert row["shap_top3_name"] == "a"

    def test_to_records_pads_when_fewer_features(self):
        vals = np.array([[0.1, -0.5]])
        result = ShapResult(
            feature_names=["a", "b"],
            shap_values=vals,
            base_value=0.0,
            method="test",
            n_items=1,
            elapsed_seconds=0.1,
        )
        records = result.to_records(k=3)
        row = records[0]
        # Only 2 features, so top3 should be padded
        assert row["shap_top1_name"] == "b"
        assert row["shap_top2_name"] == "a"
        assert row["shap_top3_name"] == ""
        assert row["shap_top3_value"] == 0.0

    def test_frozen(self):
        result = ShapResult(
            feature_names=["a"],
            shap_values=np.array([[0.1]]),
            base_value=0.0,
            method="test",
            n_items=1,
            elapsed_seconds=0.0,
        )
        with pytest.raises(AttributeError):
            result.method = "changed"  # type: ignore[misc]


# ── Feature group builder ────────────────────────────────────────────


class TestBuildFeatureGroups:
    def test_groups_cover_full_dim(self):
        emb_dim, n_discrete, n_cosine = 384, 11, 200
        groups = _build_feature_groups(emb_dim, n_discrete, n_cosine)
        total = sum(end - start for _, start, end in groups)
        assert total == emb_dim * 2 + n_discrete + n_cosine

    def test_group_names(self):
        groups = _build_feature_groups(384, 11, 100)
        names = [g[0] for g in groups]
        assert names[0] == "full_embedding"
        assert names[1] == "value_only_embedding"
        assert "cardinality" in names
        assert "null_ratio" in names
        assert names[-1] == "cosine_similarities"

    def test_no_cosine_features(self):
        groups = _build_feature_groups(384, 11, 0)
        names = [g[0] for g in groups]
        assert "cosine_similarities" not in names

    def test_no_discrete_features(self):
        groups = _build_feature_groups(384, 0, 100)
        names = [g[0] for g in groups]
        assert "cardinality" not in names


# ── CatBoost TreeSHAP integration ────────────────────────────────────


class TestCatBoostShap:
    def test_basic_multiclass(self):
        """Train a small CatBoost model and verify SHAP output shape."""
        from catboost import CatBoostClassifier

        np.random.seed(42)
        n_train, n_eval = 30, 5
        emb_dim, n_discrete, n_cosine = 4, 3, 2
        total_dim = emb_dim * 2 + n_discrete + n_cosine
        n_classes = 3

        X_train = np.random.randn(n_train, total_dim)
        y_train = np.random.randint(0, n_classes, n_train)
        X_eval = np.random.randn(n_eval, total_dim)

        cb = CatBoostClassifier(
            loss_function="MultiClass",
            classes_count=n_classes,
            depth=3,
            iterations=10,
            verbose=0,
            random_seed=42,
        )
        cb.fit(X_train, y_train)

        proba = cb.predict_proba(X_eval)
        predicted = np.argmax(proba, axis=1)

        result = run_catboost_shap(
            model=cb,
            X_eval=X_eval,
            predicted_indices=predicted,
            emb_dim=emb_dim,
            n_discrete=n_discrete,
        )

        assert isinstance(result, ShapResult)
        assert result.method == "catboost_treeshap"
        assert result.n_items == n_eval

        # Feature groups: full_emb + vo_emb + 3 discrete + cosine_sims = 6 groups
        expected_groups = 2 + n_discrete + 1  # 2 embeddings + 3 discrete + 1 cosine
        assert len(result.feature_names) == expected_groups
        assert result.shap_values.shape == (n_eval, expected_groups)

    def test_top_features_non_empty(self):
        """TreeSHAP top features should have non-empty names and values."""
        from catboost import CatBoostClassifier

        np.random.seed(42)
        emb_dim, n_discrete, n_cosine = 4, 3, 2
        total_dim = emb_dim * 2 + n_discrete + n_cosine

        X_train = np.random.randn(30, total_dim)
        y_train = np.random.randint(0, 3, 30)
        X_eval = np.random.randn(3, total_dim)

        cb = CatBoostClassifier(
            loss_function="MultiClass", classes_count=3,
            depth=3, iterations=10, verbose=0, random_seed=42,
        )
        cb.fit(X_train, y_train)

        predicted = np.argmax(cb.predict_proba(X_eval), axis=1)

        result = run_catboost_shap(
            model=cb, X_eval=X_eval, predicted_indices=predicted,
            emb_dim=emb_dim, n_discrete=n_discrete,
        )

        records = result.to_records(k=3)
        assert len(records) == 3
        for row in records:
            assert row["shap_top1_name"] != ""
            # At least the top feature should have a non-zero value
            assert row["shap_top1_value"] != 0.0

    def test_elapsed_positive(self):
        """SHAP computation should report positive elapsed time."""
        from catboost import CatBoostClassifier

        np.random.seed(42)
        X = np.random.randn(20, 13)
        y = np.random.randint(0, 2, 20)

        cb = CatBoostClassifier(
            loss_function="MultiClass", classes_count=2,
            depth=2, iterations=5, verbose=0, random_seed=42,
        )
        cb.fit(X, y)

        predicted = np.argmax(cb.predict_proba(X[:3]), axis=1)
        result = run_catboost_shap(
            model=cb, X_eval=X[:3], predicted_indices=predicted,
            emb_dim=4, n_discrete=3,
        )
        assert result.elapsed_seconds > 0


# ── Config integration ───────────────────────────────────────────────


class TestShapConfig:
    def test_shap_enabled_in_config(self):
        from sigint.config import load_config

        cfg = load_config()
        assert hasattr(cfg, "shap_enabled")
        assert cfg.shap_enabled is True

    def test_shap_hocon_mapping(self):
        from sigint.config import _HOCON_MAP

        assert "shap.enabled" in _HOCON_MAP
        field_name, field_type = _HOCON_MAP["shap.enabled"]
        assert field_name == "shap_enabled"
        assert field_type is bool
