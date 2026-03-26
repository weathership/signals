"""Tests for llm_to_mass() evidence-to-mass converter."""

from __future__ import annotations

import pytest

from sigint.belief import FrameOfDiscernment
from sigint.category_set import sigdg_category_set
from sigint.mass_functions import llm_to_mass


def _make_frame():
    cs = sigdg_category_set(hierarchical=True)
    return FrameOfDiscernment(cs), cs


class TestLlmToMass:
    def test_primary_prediction_gets_confidence_mass(self):
        frame, _ = _make_frame()
        ba = llm_to_mass("0085", 0.9, [], frame, discount=0.10)

        # Primary should get 0.9 * 0.90 = 0.81
        m_primary = ba.masses[frame.singleton("0085")]
        assert abs(m_primary - 0.81) < 1e-10

    def test_alternatives_distribute_remaining(self):
        frame, _ = _make_frame()
        alts = [
            {"code": "0076", "confidence": 0.06},
            {"code": "0013", "confidence": 0.04},
        ]
        ba = llm_to_mass("0085", 0.9, alts, frame, discount=0.10)

        # Remaining evidence = 0.90 - 0.81 = 0.09
        # Alt total = 0.10, so 0076 gets 0.06/0.10 * 0.09 = 0.054
        m_alt1 = ba.masses.get(frame.singleton("0076"), 0.0)
        assert abs(m_alt1 - 0.054) < 1e-10

        m_alt2 = ba.masses.get(frame.singleton("0013"), 0.0)
        assert abs(m_alt2 - 0.036) < 1e-10

    def test_discount_goes_to_theta(self):
        frame, _ = _make_frame()
        ba = llm_to_mass("0085", 0.95, [], frame, discount=0.10)

        # Theta should be at least discount
        m_theta = ba.masses.get(frame.theta, 0.0)
        assert m_theta >= 0.10

    def test_null_code_returns_vacuous(self):
        frame, _ = _make_frame()
        ba = llm_to_mass(None, 0.0, [], frame)
        assert ba.masses.get(frame.theta, 0.0) == pytest.approx(1.0)

    def test_unknown_code_returns_vacuous(self):
        frame, _ = _make_frame()
        ba = llm_to_mass("9999", 0.8, [], frame)
        assert ba.masses.get(frame.theta, 0.0) == pytest.approx(1.0)

    def test_default_discount_is_low(self):
        """LLM discount should be lower than cosine (0.30) and SVM (0.20)."""
        frame, _ = _make_frame()
        ba = llm_to_mass("0085", 1.0, [], frame)
        m_theta = ba.masses.get(frame.theta, 0.0)
        assert m_theta == pytest.approx(0.10)

    def test_masses_sum_to_one(self):
        frame, _ = _make_frame()
        alts = [{"code": "0076", "confidence": 0.05}]
        ba = llm_to_mass("0085", 0.85, alts, frame, discount=0.15)
        total = sum(ba.masses.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_zero_confidence_primary(self):
        frame, _ = _make_frame()
        alts = [{"code": "0076", "confidence": 0.5}]
        ba = llm_to_mass("0085", 0.0, alts, frame, discount=0.10)
        # Primary gets 0 mass, all evidence goes to alternatives
        m_primary = ba.masses.get(frame.singleton("0085"), 0.0)
        assert m_primary == 0.0
        total = sum(ba.masses.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_alt_with_unknown_code_skipped(self):
        frame, _ = _make_frame()
        alts = [{"code": "9999", "confidence": 0.1}]
        ba = llm_to_mass("0085", 0.9, alts, frame, discount=0.10)
        # Unknown alt should not appear; mass still sums to 1
        total = sum(ba.masses.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_is_valid_mass_function(self):
        frame, _ = _make_frame()
        alts = [
            {"code": "0076", "confidence": 0.03},
            {"code": "0074", "confidence": 0.02},
        ]
        ba = llm_to_mass("0085", 0.9, alts, frame, discount=0.10)
        assert ba.is_valid
