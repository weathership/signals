"""Tests for the embedding classifier (all model calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock

from sigint.category_set import CategorySet, ReferenceCategory, is_data_column
from sigint.classifier import HierarchicalClassification
from sigint.embedding_classifier import (
    EmbeddingClassifier,
    EmbeddingClassifierConfig,
    _detect_device,
    build_embedding_text,
    _camel_to_words,
    _build_category_text,
    _get_leaf_categories,
)
from sigint.ontology import CATEGORY_BY_CODE
from sigint.sampler import ColumnSample

import numpy as np


def _make_sample(name="ssn", col_type="STRING", values=None):
    return ColumnSample(
        column_name=name,
        column_type=col_type,
        values=values or ["123-45-6789", "987-65-4321"],
    )


# ── build_embedding_text tests ──────────────────────────────────────


class TestBuildEmbeddingText:
    def test_humanizes_column_name(self):
        s = _make_sample("payment_card_number", "STRING", [])
        text = build_embedding_text(s, include_values=False)
        assert text == "payment card number"

    def test_includes_non_string_type(self):
        s = _make_sample("age", "INT", [])
        text = build_embedding_text(s, include_values=False)
        assert text == "age | int"

    def test_excludes_string_type(self):
        s = _make_sample("name", "STRING", [])
        text = build_embedding_text(s, include_values=False)
        assert text == "name"

    def test_excludes_varchar_type(self):
        s = _make_sample("name", "VARCHAR", [])
        text = build_embedding_text(s, include_values=False)
        assert text == "name"

    def test_includes_values(self):
        s = _make_sample("email", "STRING", ["a@b.com", "c@d.org"])
        text = build_embedding_text(s, include_values=True, max_values=5)
        assert "a@b.com, c@d.org" in text

    def test_truncates_long_values(self):
        long_val = "x" * 200
        s = _make_sample("data", "STRING", [long_val])
        text = build_embedding_text(s, include_values=True, max_values=5)
        # Value should be truncated to 80 chars
        assert len(long_val) == 200
        assert "x" * 80 in text
        assert "x" * 81 not in text

    def test_limits_max_values(self):
        s = _make_sample("col", "STRING", ["a", "b", "c", "d", "e", "f"])
        text = build_embedding_text(s, include_values=True, max_values=3)
        assert "a, b, c" in text
        assert "d" not in text

    def test_no_values_when_disabled(self):
        s = _make_sample("col", "STRING", ["val1", "val2"])
        text = build_embedding_text(s, include_values=False)
        assert "val1" not in text

    def test_pipe_separator(self):
        s = _make_sample("credit_score", "FLOAT", ["750", "680"])
        text = build_embedding_text(s, include_values=True, max_values=5)
        assert " | " in text


# ── is_data_column tests ────────────────────────────────────────────


class TestIsDataColumn:
    def test_real_columns(self):
        assert is_data_column("payment_card_number") is True
        assert is_data_column("email") is True
        assert is_data_column("credit_score") is True

    def test_annotation_columns(self):
        assert is_data_column("attr_1_1_1_1_1_1_1") is False
        assert is_data_column("ref_1_1_1_2_2") is False
        assert is_data_column("code_1_1_1_1_2_1") is False
        assert is_data_column("var_1_1_1_2_1_1") is False
        assert is_data_column("key_1_1_1_4_1_1") is False
        assert is_data_column("data_1_1_1_3_1") is False
        assert is_data_column("field_1_1_1_7_4_2_1") is False
        assert is_data_column("col_0_day_security_flaw") is False
        assert is_data_column("item_something") is False
        assert is_data_column("val_something") is False

    def test_row_id(self):
        assert is_data_column("row_id") is False

    def test_table_prefixed_columns(self):
        assert is_data_column("personal_data.payment_card_number") is True
        assert is_data_column("personal_data.attr_1_1_1_1_1_1_1") is False
        assert is_data_column("personal_data.row_id") is False


# ── Helper function tests ───────────────────────────────────────────


class TestHelpers:
    def test_camel_to_words(self):
        assert _camel_to_words("PaymentCardData") == "payment card data"
        assert _camel_to_words("SSN") == "ssn"  # all caps stays together
        assert _camel_to_words("EmailAddress") == "email address"

    def test_leaf_categories_excludes_parents(self):
        leaves = _get_leaf_categories()
        leaf_codes = {c.code for c in leaves}
        # Root "0001" should not be a leaf
        assert "0001" not in leaf_codes
        # "IdentityInformation" (0010) is a parent
        assert "0010" not in leaf_codes
        # "TaxIdentifier" (0085) IS a leaf
        assert "0085" in leaf_codes

    def test_category_text_format(self):
        cat = CATEGORY_BY_CODE["0085"]
        text = _build_category_text(cat)
        assert "tax identifier" in text
        assert "TIN" in text
        assert "SSN" in text


# ── DST classification ───────────────────────────────────────────────


class TestClassification:
    def _make_classifier_with_mock_model(self, dim=384):
        """Create an EmbeddingClassifier with a mocked SentenceTransformer.

        Uses sigdg taxonomy (hierarchical=True by default).
        """
        cfg = EmbeddingClassifierConfig(confidence_threshold=0.01)
        clf = EmbeddingClassifier(cfg)

        mock_model = MagicMock()

        # Pre-compute: category embeddings — one-hot style for predictability
        n_cats = len(clf._category_set.categories)
        cat_embs = np.eye(n_cats, dim)

        def mock_encode(texts, batch_size=32):
            if len(texts) == n_cats:
                return cat_embs
            # Single item — return a vector pointing at category 0
            vec = np.zeros((1, dim))
            vec[0, 0] = 1.0  # aligns with category index 0
            return vec

        mock_model.encode = mock_encode
        clf._model = mock_model
        return clf

    def test_returns_hierarchical_classification(self):
        clf = self._make_classifier_with_mock_model()
        sample = _make_sample("ssn", "STRING", ["123-45-6789"])
        result = clf.classify(sample)

        assert result is not None
        assert isinstance(result, HierarchicalClassification)
        assert result.confidence > 0

    def test_result_has_dst_evidence(self):
        clf = self._make_classifier_with_mock_model()
        result = clf.classify(_make_sample())
        assert result is not None
        assert "dst(" in result.evidence
        assert "Bel=" in result.evidence
        assert "Pl=" in result.evidence

    def test_result_has_belief_assignment(self):
        clf = self._make_classifier_with_mock_model()
        result = clf.classify(_make_sample())
        assert result is not None
        assert result.belief_assignment is not None

    def test_result_has_source_masses(self):
        clf = self._make_classifier_with_mock_model()
        result = clf.classify(_make_sample())
        assert result is not None
        assert "cosine" in result.source_masses
        assert "name_match" in result.source_masses

    def test_boost_always_zero(self):
        """Name match is now a mass function, not a boost — boost field is 0."""
        clf = self._make_classifier_with_mock_model()
        result = clf.classify(_make_sample("date_of_birth", "STRING", ["1990-01-15"]))
        assert result is not None
        assert result.boost == 0.0

    def test_name_match_in_evidence_sources(self):
        """Name match evidence appears in source_masses."""
        clf = self._make_classifier_with_mock_model()
        result = clf.classify(_make_sample("email", "STRING", ["a@b.com"]))
        assert result is not None
        assert "name_match" in result.source_masses

    def test_category_embeddings_cached(self):
        cfg = EmbeddingClassifierConfig(confidence_threshold=0.01)
        clf = EmbeddingClassifier(cfg)

        n_cats = len(clf._category_set.categories)
        dim = 384
        cat_embs = np.eye(n_cats, dim)

        mock_model = MagicMock()

        def mock_encode(texts, batch_size=32):
            if len(texts) == n_cats:
                return cat_embs
            vec = np.zeros((1, dim))
            vec[0, 0] = 1.0
            return vec

        mock_model.encode = MagicMock(side_effect=mock_encode)
        clf._model = mock_model

        sample = _make_sample()

        # First call computes category embeddings
        clf.classify(sample)
        call_count_1 = clf._model.encode.call_count

        # Second call should not re-encode categories
        clf.classify(sample)
        call_count_2 = clf._model.encode.call_count

        # Only one extra call for the second sample, not categories again
        assert call_count_2 == call_count_1 + 1

    def test_result_has_sensitivity(self):
        clf = self._make_classifier_with_mock_model()
        result = clf.classify(_make_sample())
        assert result is not None
        # The matched category should have a sensitivity code if defined
        code = result.category.code
        from sigint.ontology import DEFAULT_SENSITIVITY
        expected = DEFAULT_SENSITIVITY.get(code)
        assert result.sensitivity_code == expected


# ── CategorySet tests ───────────────────────────────────────────────


class TestCategorySet:
    def test_sigdg_category_set_produces_leaves(self):
        from sigint.category_set import sigdg_category_set
        cs = sigdg_category_set()
        assert cs.name == "sigdg"
        # Should have the same number as _get_leaf_categories
        leaves = _get_leaf_categories()
        assert len(cs.categories) == len(leaves)
        # Every category should have embedding_text
        for cat in cs.categories:
            assert cat.embedding_text
            assert cat.taxonomy == "sigdg"

    def test_sigdg_by_code_lookup(self):
        from sigint.category_set import sigdg_category_set
        cs = sigdg_category_set()
        tin = cs.by_code.get("0085")
        assert tin is not None
        assert tin.label == "TaxIdentifier"
        assert tin.abbrev == "TIN"

    def test_annotation_category_set(self, tmp_path):
        from sigint.category_set import annotation_category_set
        # Create a minimal annotations.csv
        ann_csv = tmp_path / "annotations.csv"
        ann_csv.write_text(
            'ID,Ontology,Annotation,Definition,Common Names,"Specifics, Examples and/or Additional Context",Deprecated\n'
            '1.1,Personally Identifiable Data,C_PID,Aggregated PII data,,test,no\n'
            '1.1.1,Personal Data,C_PD,Personal data elements,,test,no\n'
            '1.1.1.1,Financial Data,C_FD,Financial data elements,,test,no\n'
            '1.1.1.1.1,Payment Data,C_BD,Payment data elements,,test,no\n'
            '1.1.1.1.1.1,Payment Card Data,C_PCD,Payment card elements,,test,no\n'
            '1.1.1.1.1.1.1,Payment Card Number,PAN,The number on a credit card,Credit Card,examples,no\n'
            '1.1.1.1.1.1.2,Card Verification Value,CVV2,CVV 3 or 4 digits,CVV,,no\n'
            '1.1.1.1.1.1.8,Masked Payment Card Number,MASKPAN,First 6 and last 4,,,yes\n'
        )
        cs = annotation_category_set(ann_csv)
        assert cs.name == "annotations"
        # Only leaves (PAN and CVV2) should be included, MASKPAN is deprecated
        codes = {c.code for c in cs.categories}
        assert "1.1.1.1.1.1.1" in codes  # PAN (leaf)
        assert "1.1.1.1.1.1.2" in codes  # CVV2 (leaf)
        assert "1.1.1.1.1.1.8" not in codes  # deprecated
        assert "1.1.1.1.1.1" not in codes  # parent
        assert "1.1" not in codes  # parent

    def test_annotation_embedding_text_rich(self, tmp_path):
        from sigint.category_set import annotation_category_set
        ann_csv = tmp_path / "annotations.csv"
        ann_csv.write_text(
            'ID,Ontology,Annotation,Definition,Common Names,"Specifics, Examples and/or Additional Context",Deprecated\n'
            '1.1.1.1.1.1.1,Payment Card Number,PAN,The number on a credit card,Credit Card; Debit Card,truncation rules,no\n'
        )
        cs = annotation_category_set(ann_csv)
        assert len(cs.categories) == 1
        cat = cs.categories[0]
        assert "PAN" in cat.embedding_text
        assert "Payment Card Number" in cat.embedding_text
        assert "credit card" in cat.embedding_text.lower()
        assert cat.abbrev == "PAN"
        assert cat.taxonomy == "annotations"


# ── Ground truth extraction tests ───────────────────────────────────


class TestGroundTruth:
    def _make_category_set(self):
        return CategorySet(
            name="test",
            categories=[
                ReferenceCategory(
                    code="1.1.1.1.1.1.1", label="Payment Card Number",
                    embedding_text="PAN", abbrev="PAN", taxonomy="annotations",
                ),
                ReferenceCategory(
                    code="1.1.1.1.1.1.2", label="Card Verification Value",
                    embedding_text="CVV2", abbrev="CVV2", taxonomy="annotations",
                ),
                ReferenceCategory(
                    code="1.1.1.2.2", label="Gender",
                    embedding_text="GENDER", abbrev="GENDER", taxonomy="annotations",
                ),
            ],
        )

    def test_extracts_truth_from_paired_headers(self):
        from sigint.category_set import extract_ground_truth
        cs = self._make_category_set()
        headers = [
            "personal_data.row_id",
            "personal_data.payment_card_number",
            "personal_data.attr_1_1_1_1_1_1_1",
            "personal_data.card_verification_value",
            "personal_data.attr_1_1_1_1_1_1_2",
            "personal_data.gender",
            "personal_data.ref_1_1_1_2_2",
        ]
        truth = extract_ground_truth(headers, cs)
        assert truth["payment_card_number"] == "1.1.1.1.1.1.1"
        assert truth["card_verification_value"] == "1.1.1.1.1.1.2"
        assert truth["gender"] == "1.1.1.2.2"

    def test_ignores_unmatched_annotation_codes(self):
        from sigint.category_set import extract_ground_truth
        cs = self._make_category_set()
        headers = [
            "data.some_column",
            "data.attr_9_9_9_9",  # code 9.9.9.9 not in category set
        ]
        truth = extract_ground_truth(headers, cs)
        assert "some_column" not in truth

    def test_handles_different_prefixes(self):
        from sigint.category_set import extract_ground_truth
        cs = self._make_category_set()
        headers = [
            "t.payment_card_number",
            "t.ref_1_1_1_1_1_1_1",
            "t.gender",
            "t.code_1_1_1_2_2",
        ]
        truth = extract_ground_truth(headers, cs)
        assert truth["payment_card_number"] == "1.1.1.1.1.1.1"
        assert truth["gender"] == "1.1.1.2.2"


# ── Custom CategorySet + DST classification ─────────────────────────


class TestCategorySetClassifier:
    def test_classifier_with_custom_category_set(self):
        cats = [
            ReferenceCategory(
                code="A", label="Email",
                embedding_text="email address electronic mail",
                abbrev="EMAIL", taxonomy="test",
            ),
            ReferenceCategory(
                code="B", label="Phone",
                embedding_text="phone number telephone mobile",
                abbrev="PHONE", taxonomy="test",
            ),
        ]
        cs = CategorySet(name="test", categories=cats)
        cfg = EmbeddingClassifierConfig(confidence_threshold=0.01)
        clf = EmbeddingClassifier(cfg, category_set=cs)

        # Mock model
        mock_model = MagicMock()
        dim = 384

        def mock_encode(texts, batch_size=32):
            if len(texts) == 2:
                # Category embeddings
                embs = np.zeros((2, dim))
                embs[0, 0] = 1.0  # Email direction
                embs[1, 1] = 1.0  # Phone direction
                return embs
            # Input — point toward Email (index 0)
            vec = np.zeros((1, dim))
            vec[0, 0] = 1.0
            return vec

        mock_model.encode = mock_encode
        clf._model = mock_model

        result = clf.classify(_make_sample("user_email", "STRING", ["a@b.com"]))
        assert result is not None
        assert isinstance(result, HierarchicalClassification)
        assert result.category.code == "A"
        assert result.category.label == "Email"
        assert result.sensitivity_code is None  # non-SIGDG taxonomy

    def test_cosine_only_path_when_name_does_not_match(self):
        """When column name doesn't match any category label, cosine alone decides."""
        cats = [
            ReferenceCategory(
                code="A", label="Payment Card Number",
                embedding_text="payment card number credit card debit card",
                abbrev="PAN", taxonomy="test",
            ),
            ReferenceCategory(
                code="B", label="Email Address",
                embedding_text="email address electronic mail",
                abbrev="EMAIL", taxonomy="test",
            ),
        ]
        cs = CategorySet(name="test", categories=cats)
        cfg = EmbeddingClassifierConfig(confidence_threshold=0.01)
        clf = EmbeddingClassifier(cfg, category_set=cs)

        mock_model = MagicMock()
        dim = 384

        def mock_encode(texts, batch_size=32):
            if len(texts) == 2:
                embs = np.zeros((2, dim))
                embs[0, 0] = 1.0  # PAN direction
                embs[1, 1] = 1.0  # Email direction
                return embs
            # "cc_num" — abbreviated name, points toward PAN
            vec = np.zeros((1, dim))
            vec[0, 0] = 0.8
            vec[0, 1] = 0.2
            return vec

        mock_model.encode = mock_encode
        clf._model = mock_model

        # Column name "cc_num" doesn't match "payment card number" — cosine evidence strongest
        result = clf.classify(_make_sample("cc_num", "STRING", ["4111111111111111"]))
        assert result is not None
        assert result.category.code == "A"  # PAN wins on cosine
        assert "dst(" in result.evidence


# ── Generality / edge case tests ─────────────────────────────────


class TestGenerality:
    def test_name_match_evidence_in_sources(self):
        """When name matches exactly, name_match appears in source_masses."""
        cats = [
            ReferenceCategory(
                code="A", label="Date Of Birth",
                embedding_text="date of birth birthday DOB",
                abbrev="DOB", taxonomy="test",
            ),
        ]
        cs = CategorySet(name="test", categories=cats)
        cfg = EmbeddingClassifierConfig(confidence_threshold=0.01)
        clf = EmbeddingClassifier(cfg, category_set=cs)

        mock_model = MagicMock()
        dim = 384

        def mock_encode(texts, batch_size=32):
            if len(texts) == 1 and len(texts[0]) > 20:
                # Category embedding
                embs = np.zeros((1, dim))
                embs[0, 0] = 1.0
                return embs
            vec = np.zeros((1, dim))
            vec[0, 0] = 0.6
            return vec

        mock_model.encode = mock_encode
        clf._model = mock_model

        # Column name "date_of_birth" → humanized "date of birth" matches exactly
        result = clf.classify(_make_sample("date_of_birth", "STRING", ["1990-01-15"]))
        assert result is not None
        assert "name_match" in result.source_masses
        assert "dst(" in result.evidence
        assert result.boost == 0.0  # boost is always 0 in DST mode

    def test_annotation_csv_missing_columns_raises(self, tmp_path):
        """annotation_category_set raises ValueError on wrong CSV format."""
        from sigint.category_set import annotation_category_set

        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("Name,Type,Value\nfoo,bar,baz\n")
        try:
            annotation_category_set(bad_csv)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "missing required columns" in str(e)

    def test_no_name_boost_ablation(self):
        """With name_match_boost=False, name_match source is absent."""
        cats = [
            ReferenceCategory(
                code="A", label="Date Of Birth",
                embedding_text="date of birth birthday DOB",
                abbrev="DOB", taxonomy="test",
            ),
        ]
        cs = CategorySet(name="test", categories=cats)
        cfg = EmbeddingClassifierConfig(
            confidence_threshold=0.01,
            name_match_boost=False,
        )
        clf = EmbeddingClassifier(cfg, category_set=cs)

        mock_model = MagicMock()
        dim = 384

        def mock_encode(texts, batch_size=32):
            embs = np.zeros((len(texts), dim))
            embs[0, 0] = 1.0
            return embs

        mock_model.encode = mock_encode
        clf._model = mock_model

        # Column name matches exactly, but name_match is disabled
        result = clf.classify(_make_sample("date_of_birth", "STRING", ["1990-01-15"]))
        assert result is not None
        assert result.boost == 0.0
        assert "name_match" not in result.source_masses


class TestDetectDevice:
    def test_returns_string(self):
        """_detect_device returns 'cuda' or 'cpu'."""
        result = _detect_device()
        assert result in ("cuda", "cpu")

    def test_returns_cpu_without_torch(self, monkeypatch):
        """Falls back to 'cpu' when torch is not importable."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("no torch")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        assert _detect_device() == "cpu"

    def test_gpu_batch_size_scaling(self, monkeypatch):
        """GPU device auto-scales batch_size from <=64 to 256."""
        import sys

        mock_st_module = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st_module)

        cfg = EmbeddingClassifierConfig(batch_size=32, device="cuda:0")
        clf = EmbeddingClassifier(cfg)
        clf._get_model()
        assert cfg.batch_size == 256


# ── Pattern evidence taxonomy map ────────────────────────────────


class TestPatternEvidenceTaxonomyMap:
    def test_pattern_evidence_uses_taxonomy_map(self):
        """Classify with features should use taxonomy-specific pattern map."""
        from sigint.features import ColumnFeatures

        cats = [
            ReferenceCategory(
                code="date", label="date",
                embedding_text="date | calendar date | values are YYYY-MM-DD",
                taxonomy="gittables",
            ),
            ReferenceCategory(
                code="id", label="id",
                embedding_text="id | unique identifier | values are integers",
                taxonomy="gittables",
            ),
        ]
        cs = CategorySet(name="gittables", categories=cats)
        cfg = EmbeddingClassifierConfig(confidence_threshold=0.01)
        clf = EmbeddingClassifier(cfg, category_set=cs)

        mock_model = MagicMock()
        dim = 384

        def mock_encode(texts, batch_size=32):
            embs = np.zeros((len(texts), dim))
            for i in range(len(texts)):
                embs[i, 0] = 1.0
            return embs

        mock_model.encode = mock_encode
        clf._model = mock_model

        features = ColumnFeatures(
            column_name_humanized="col0",
            column_type=None,
            sample_values_text="2024-01-15",
            cardinality=1,
            null_ratio=None,
            value_entropy=0.0,
            pattern_signals=["date_iso_pattern"],
            is_generic_name=True,
            value_description="column of date values in YYYY-MM-DD format",
        )

        result = clf.classify(
            _make_sample("col0", "STRING", ["2024-01-15"]),
            features=features,
        )
        assert result is not None
        # Pattern evidence should be present since we have pattern_signals
        assert "patterns" in result.source_masses
