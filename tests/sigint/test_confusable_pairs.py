"""Tests for confusable pairs registry."""

from __future__ import annotations

from sigint.confusable_pairs import (
    ANNOTATION_CONFUSABLE_PAIRS,
    SIGDG_CONFUSABLE_PAIRS,
    get_confusable_pairs,
)


class TestConfusablePairsRegistry:
    def test_annotation_pairs_count(self):
        assert len(ANNOTATION_CONFUSABLE_PAIRS) == 11

    def test_sigdg_pairs_count(self):
        assert len(SIGDG_CONFUSABLE_PAIRS) == 1

    def test_get_annotations(self):
        pairs = get_confusable_pairs("annotations")
        assert pairs is ANNOTATION_CONFUSABLE_PAIRS

    def test_get_sigdg(self):
        pairs = get_confusable_pairs("sigdg")
        assert pairs is SIGDG_CONFUSABLE_PAIRS

    def test_get_unknown_taxonomy_returns_empty(self):
        pairs = get_confusable_pairs("unknown")
        assert pairs == []

    def test_all_sigdg_codes_exist_in_taxonomy(self):
        from sigint.category_set import sigdg_category_set

        cs = sigdg_category_set(hierarchical=True)
        all_codes = {c.code for c in cs.all_categories}
        for a, b in SIGDG_CONFUSABLE_PAIRS:
            assert a in all_codes, f"SIGDG code {a} not in taxonomy"
            assert b in all_codes, f"SIGDG code {b} not in taxonomy"
