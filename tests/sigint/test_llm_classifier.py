"""Tests for the LLM classifier (all API calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sigint.llm_classifier import LLMClassifier, LLMClassifierConfig, load_annotations
from sigint.ontology import CATEGORIES, CATEGORY_BY_CODE
from sigint.sampler import ColumnSample


def _make_sample(name="ssn", col_type="STRING", values=None):
    return ColumnSample(
        column_name=name,
        column_type=col_type,
        values=values or ["123-45-6789", "987-65-4321"],
    )


def _mock_response(text: str):
    """Build a mock Anthropic message response."""
    content_block = MagicMock()
    content_block.text = text
    resp = MagicMock()
    resp.content = [content_block]
    return resp


class TestLLMClassifier:
    def test_classify_parses_valid_json(self):
        cfg = LLMClassifierConfig(api_key="test-key")
        clf = LLMClassifier(cfg)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            '{"category_code": "0085", "confidence": 0.95, '
            '"evidence": "SSN pattern match"}'
        )
        clf._client = mock_client

        result = clf.classify(_make_sample())
        assert result is not None
        assert result.category.code == "0085"
        assert result.category.label == "TaxIdentifier"
        assert result.confidence == 0.95
        assert result.evidence == "SSN pattern match"
        assert result.sensitivity_code == "1040"

    def test_classify_returns_none_on_bad_response(self):
        cfg = LLMClassifierConfig(api_key="test-key")
        clf = LLMClassifier(cfg)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            "I'm not sure what this column is."
        )
        clf._client = mock_client

        result = clf.classify(_make_sample())
        assert result is None

    def test_classify_returns_none_on_null_json(self):
        cfg = LLMClassifierConfig(api_key="test-key")
        clf = LLMClassifier(cfg)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response("null")
        clf._client = mock_client

        result = clf.classify(_make_sample())
        assert result is None

    def test_classify_returns_none_on_unknown_code(self):
        cfg = LLMClassifierConfig(api_key="test-key")
        clf = LLMClassifier(cfg)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            '{"category_code": "9999", "confidence": 0.8, "evidence": "unknown"}'
        )
        clf._client = mock_client

        result = clf.classify(_make_sample())
        assert result is None

    def test_classify_strips_markdown_fencing(self):
        cfg = LLMClassifierConfig(api_key="test-key")
        clf = LLMClassifier(cfg)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            '```json\n'
            '{"category_code": "0076", "confidence": 0.88, '
            '"evidence": "email column"}\n'
            '```'
        )
        clf._client = mock_client

        result = clf.classify(_make_sample("email", "STRING", ["a@b.com"]))
        assert result is not None
        assert result.category.code == "0076"

    def test_missing_api_key_raises(self):
        cfg = LLMClassifierConfig(api_key=None)
        clf = LLMClassifier(cfg)

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises((ValueError, ImportError)):
                clf._get_client()

    def test_system_prompt_contains_categories(self):
        cfg = LLMClassifierConfig(api_key="test-key")
        clf = LLMClassifier(cfg)

        prompt = clf._build_system_prompt()

        # All leaf categories should be in the prompt
        leaf_codes = {c.code for c in CATEGORIES} - {
            c.parent_code for c in CATEGORIES if c.parent_code
        }
        for code in leaf_codes:
            cat = CATEGORY_BY_CODE[code]
            assert cat.label in prompt, f"Missing leaf {cat.label} in system prompt"

    def test_annotations_in_prompt(self):
        vocab = [
            {"annotation": "PAN", "description": "Primary Account Number"},
            {"annotation": "CVV", "description": "Card Verification Value"},
        ]
        cfg = LLMClassifierConfig(api_key="test-key", annotations_vocabulary=vocab)
        clf = LLMClassifier(cfg)

        prompt = clf._build_system_prompt()
        assert "PAN" in prompt
        assert "Primary Account Number" in prompt
        assert "Reference Vocabulary" in prompt

    def test_siblings_in_user_prompt(self):
        cfg = LLMClassifierConfig(api_key="test-key")
        clf = LLMClassifier(cfg)

        target = _make_sample("ssn")
        siblings = [
            _make_sample("ssn"),
            _make_sample("first_name", "STRING", ["Alice", "Bob"]),
            _make_sample("phone", "STRING", ["555-1234"]),
        ]

        prompt = clf._build_user_prompt(target, siblings)
        assert "first_name" in prompt
        assert "phone" in prompt
        # Target column should not appear in siblings list
        assert "Sibling columns" in prompt


class TestLoadAnnotations:
    def test_load_csv(self, tmp_path):
        csv_file = tmp_path / "annotations.csv"
        csv_file.write_text(
            "annotation,description\n"
            "PAN,Primary Account Number\n"
            "CVV,Card Verification Value\n"
        )

        rows = load_annotations(csv_file)
        assert len(rows) == 2
        assert rows[0]["annotation"] == "PAN"
        assert rows[1]["description"] == "Card Verification Value"
