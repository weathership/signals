"""Tests for HierarchicalClassification and classify()."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from sigint.belief import BeliefAssignment, FocalElement, FrameOfDiscernment
from sigint.category_set import sigdg_category_set
from sigint.classifier import HierarchicalClassification
from sigint.embedding_classifier import (
    EmbeddingClassifier,
    EmbeddingClassifierConfig,
    _get_leaf_categories,
)
from sigint.sampler import ColumnSample


def _make_sample(name="ssn", col_type="STRING", values=None):
    return ColumnSample(
        column_name=name,
        column_type=col_type,
        values=values or ["123-45-6789", "987-65-4321"],
    )


def _make_frame():
    cs = sigdg_category_set(hierarchical=True)
    return FrameOfDiscernment(cs), cs


class TestHierarchicalClassificationFields:
    def test_backward_compat_fields(self):
        """category, confidence, evidence are accessible."""
        frame, cs = _make_frame()
        cat = cs.by_code["0085"]
        hc = HierarchicalClassification(
            category=cat,
            confidence=0.85,
            evidence="test evidence",
            sensitivity_code="1040",
        )
        assert hc.category.code == "0085"
        assert hc.confidence == 0.85
        assert hc.evidence == "test evidence"
        assert hc.sensitivity_code == "1040"

    def test_atlas_type_name(self):
        frame, cs = _make_frame()
        cat = cs.by_code["0085"]
        hc = HierarchicalClassification(category=cat, confidence=0.85, evidence="test")
        assert "SIGDG" in hc.atlas_type_name


class TestBeliefMethods:
    def test_belief_at_leaf(self):
        """belief_at for a leaf code returns Bel(singleton)."""
        frame, cs = _make_frame()
        tin = frame.singleton("0085")
        ba = BeliefAssignment(masses={tin: 0.7, frame.theta: 0.3})

        hc = HierarchicalClassification(
            category=cs.by_code["0085"],
            confidence=0.7,
            evidence="test",
            belief_assignment=ba,
            _frame=frame,
            _category_set=cs,
        )
        assert abs(hc.belief_at("0085") - 0.7) < 1e-9

    def test_plausibility_at_leaf(self):
        """plausibility_at for a leaf includes Theta mass."""
        frame, cs = _make_frame()
        tin = frame.singleton("0085")
        ba = BeliefAssignment(masses={tin: 0.6, frame.theta: 0.4})

        hc = HierarchicalClassification(
            category=cs.by_code["0085"],
            confidence=0.6,
            evidence="test",
            belief_assignment=ba,
            _frame=frame,
            _category_set=cs,
        )
        assert abs(hc.plausibility_at("0085") - 1.0) < 1e-9  # 0.6 + 0.4

    def test_belief_at_internal(self):
        """belief_at for an internal code returns Bel over descendants."""
        frame, cs = _make_frame()
        tin = frame.singleton("0085")
        ba = BeliefAssignment(masses={tin: 0.7, frame.theta: 0.3})

        hc = HierarchicalClassification(
            category=cs.by_code["0085"],
            confidence=0.7,
            evidence="test",
            belief_assignment=ba,
            _frame=frame,
            _category_set=cs,
        )
        # 0085 is under 0011 (GovernmentIdentifier)
        # Bel(0011) >= Bel(0085) since {0085} ⊆ descendants(0011)
        bel_parent = hc.belief_at("0011")
        bel_leaf = hc.belief_at("0085")
        assert bel_parent >= bel_leaf

    def test_interval_at(self):
        frame, cs = _make_frame()
        tin = frame.singleton("0085")
        ba = BeliefAssignment(masses={tin: 0.6, frame.theta: 0.4})

        hc = HierarchicalClassification(
            category=cs.by_code["0085"],
            confidence=0.6,
            evidence="test",
            belief_assignment=ba,
            _frame=frame,
            _category_set=cs,
        )
        bel, pl = hc.interval_at("0085")
        assert bel <= pl

    def test_uncertainty_gap(self):
        frame, cs = _make_frame()
        tin = frame.singleton("0085")
        ba = BeliefAssignment(masses={tin: 0.6, frame.theta: 0.4})

        hc = HierarchicalClassification(
            category=cs.by_code["0085"],
            confidence=0.6,
            evidence="test",
            belief_assignment=ba,
            _frame=frame,
            _category_set=cs,
        )
        gap = hc.uncertainty_gap
        assert gap == abs(hc.plausibility_at("0085") - hc.belief_at("0085"))

    def test_needs_clarification_high_gap(self):
        frame, cs = _make_frame()
        tin = frame.singleton("0085")
        # Very uncertain: small mass on singleton, large on theta
        ba = BeliefAssignment(masses={tin: 0.2, frame.theta: 0.8})

        hc = HierarchicalClassification(
            category=cs.by_code["0085"],
            confidence=0.2,
            evidence="test",
            belief_assignment=ba,
            _frame=frame,
            _category_set=cs,
        )
        assert hc.needs_clarification  # gap = 0.8 > 0.3

    def test_needs_clarification_high_conflict(self):
        frame, cs = _make_frame()
        tin = frame.singleton("0085")
        ba = BeliefAssignment(masses={tin: 0.9, frame.theta: 0.1})

        hc = HierarchicalClassification(
            category=cs.by_code["0085"],
            confidence=0.9,
            evidence="test",
            belief_assignment=ba,
            conflict=0.25,
            _frame=frame,
            _category_set=cs,
        )
        assert hc.needs_clarification  # conflict 0.25 > 0.2

    def test_no_clarification_when_confident(self):
        frame, cs = _make_frame()
        tin = frame.singleton("0085")
        ba = BeliefAssignment(masses={tin: 0.9, frame.theta: 0.1})

        hc = HierarchicalClassification(
            category=cs.by_code["0085"],
            confidence=0.9,
            evidence="test",
            belief_assignment=ba,
            conflict=0.05,
            _frame=frame,
            _category_set=cs,
        )
        assert not hc.needs_clarification


class TestFromCombinedEvidence:
    def test_basic_combination(self):
        """from_combined_evidence produces a valid HierarchicalClassification."""
        frame, cs = _make_frame()
        from sigint.mass_functions import cosine_to_mass, name_match_to_mass

        sims = {"0085": 0.9, "0076": 0.2}
        sources = {
            "cosine": cosine_to_mass(sims, frame, discount=0.3),
            "name_match": name_match_to_mass("tax_identifier", frame, cs),
        }

        hc = HierarchicalClassification.from_combined_evidence(
            source_masses=sources,
            frame=frame,
            category_set=cs,
        )

        assert hc.category.code == "0085"
        assert hc.confidence > 0
        assert "dst(" in hc.evidence
        assert "Bel=" in hc.evidence
        assert hc.belief_assignment is not None

    def test_evidence_string_format(self):
        """Evidence string includes source names and belief interval."""
        frame, cs = _make_frame()
        from sigint.mass_functions import cosine_to_mass

        sources = {
            "cosine": cosine_to_mass({"0085": 0.95}, frame, discount=0.2),
        }
        hc = HierarchicalClassification.from_combined_evidence(
            source_masses=sources,
            frame=frame,
            category_set=cs,
        )
        assert "cosine=" in hc.evidence
        assert "Bel=" in hc.evidence
        assert "Pl=" in hc.evidence


class TestClassify:
    def _make_classifier_with_mock(self, dim=384):
        cs = sigdg_category_set(hierarchical=True)
        cfg = EmbeddingClassifierConfig(confidence_threshold=0.01)
        clf = EmbeddingClassifier(cfg, category_set=cs)

        mock_model = MagicMock()
        n_cats = len(cs.categories)
        cat_embs = np.eye(n_cats, dim)

        def mock_encode(texts, batch_size=32):
            if len(texts) == n_cats:
                return cat_embs
            vec = np.zeros((1, dim))
            vec[0, 0] = 1.0
            return vec

        mock_model.encode = mock_encode
        clf._model = mock_model
        return clf

    def test_classify_returns_hierarchical(self):
        """classify returns HierarchicalClassification."""
        clf = self._make_classifier_with_mock()
        sample = _make_sample("tax_identifier", "STRING", ["123-45-6789"])

        result = clf.classify(sample)
        assert isinstance(result, HierarchicalClassification)
        assert result.belief_assignment is not None
        assert result.confidence > 0

    def test_classify_has_source_masses(self):
        """Source masses include at least cosine and name_match."""
        clf = self._make_classifier_with_mock()
        sample = _make_sample("email_address", "STRING", ["a@b.com"])

        result = clf.classify(sample)
        assert "cosine" in result.source_masses
        assert "name_match" in result.source_masses
