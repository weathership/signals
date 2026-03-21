"""Tests for evidence-to-mass converters."""

from __future__ import annotations

from sigint.belief import FrameOfDiscernment
from sigint.category_set import sigdg_category_set
from sigint.mass_functions import (
    catboost_to_mass,
    cosine_to_mass,
    name_match_to_mass,
    pattern_to_mass,
)


def _make_frame():
    cs = sigdg_category_set(hierarchical=True)
    return FrameOfDiscernment(cs), cs


class TestCosineToMass:
    def test_high_confidence_concentrated(self):
        """High similarity to one code → concentrated mass."""
        frame, cs = _make_frame()
        sims = {"0085": 0.95, "0076": 0.2, "0074": 0.1}
        ba = cosine_to_mass(sims, frame, discount=0.3)
        assert ba.is_valid
        # TaxIdentifier should get most mass
        tin_mass = ba.masses.get(frame.singleton("0085"), 0.0)
        assert tin_mass > 0.3

    def test_uniform_input_spread_mass(self):
        """Uniform similarities → spread mass."""
        frame, cs = _make_frame()
        sims = {code: 0.5 for code in list(frame.singletons.keys())[:5]}
        ba = cosine_to_mass(sims, frame, discount=0.3)
        assert ba.is_valid
        # Each should get roughly equal mass
        masses = [
            ba.masses.get(frame.singleton(code), 0.0)
            for code in list(frame.singletons.keys())[:5]
        ]
        assert max(masses) - min(masses) < 0.05

    def test_empty_returns_vacuous(self):
        frame, _ = _make_frame()
        ba = cosine_to_mass({}, frame)
        assert ba.is_valid
        assert ba.masses[frame.theta] == 1.0

    def test_discount_controls_theta(self):
        frame, _ = _make_frame()
        sims = {"0085": 0.9}
        ba = cosine_to_mass(sims, frame, discount=0.5)
        assert abs(ba.masses[frame.theta] - 0.5) < 1e-9


class TestCatBoostToMass:
    def test_high_probability_concentrated(self):
        frame, _ = _make_frame()
        proba = {"0085": 0.9, "0076": 0.05, "0074": 0.05}
        ba = catboost_to_mass(proba, frame)
        assert ba.is_valid
        tin_mass = ba.masses.get(frame.singleton("0085"), 0.0)
        assert tin_mass > 0.5

    def test_empty_returns_vacuous(self):
        frame, _ = _make_frame()
        ba = catboost_to_mass({}, frame)
        assert ba.is_valid
        assert ba.masses[frame.theta] == 1.0

    def test_high_variance_increases_discount(self):
        """High virtual ensemble variance → more mass on Theta."""
        frame, _ = _make_frame()
        proba = {"0085": 0.9, "0076": 0.1}
        variance = {"0085": 0.2, "0076": 0.2}

        ba_high_var = catboost_to_mass(proba, frame, virtual_ensembles_variance=variance)
        ba_no_var = catboost_to_mass(proba, frame)

        # Higher variance → more theta mass
        assert ba_high_var.masses[frame.theta] > ba_no_var.masses[frame.theta]


class TestPatternToMass:
    def test_email_pattern_maps_to_email(self):
        frame, _ = _make_frame()
        ba = pattern_to_mass(["email_pattern"], frame)
        assert ba.is_valid
        email_mass = ba.masses.get(frame.singleton("0076"), 0.0)
        assert email_mass > 0.5

    def test_multiple_patterns(self):
        frame, _ = _make_frame()
        ba = pattern_to_mass(["email_pattern", "phone_pattern"], frame)
        assert ba.is_valid
        email_mass = ba.masses.get(frame.singleton("0076"), 0.0)
        phone_mass = ba.masses.get(frame.singleton("0074"), 0.0)
        assert email_mass > 0
        assert phone_mass > 0

    def test_no_patterns_returns_vacuous(self):
        frame, _ = _make_frame()
        ba = pattern_to_mass([], frame)
        assert ba.is_valid
        assert ba.masses[frame.theta] == 1.0

    def test_unknown_pattern_returns_vacuous(self):
        frame, _ = _make_frame()
        ba = pattern_to_mass(["unknown_pattern"], frame)
        assert ba.is_valid
        assert ba.masses[frame.theta] == 1.0


class TestNameMatchToMass:
    def test_exact_match(self):
        frame, cs = _make_frame()
        # "tax identifier" matches TaxIdentifier exactly
        ba = name_match_to_mass("tax_identifier", frame, cs)
        assert ba.is_valid
        tin_mass = ba.masses.get(frame.singleton("0085"), 0.0)
        assert abs(tin_mass - 0.7) < 1e-9

    def test_abbrev_match(self):
        frame, cs = _make_frame()
        # "tin" matches TIN abbreviation
        ba = name_match_to_mass("tin", frame, cs)
        assert ba.is_valid
        tin_mass = ba.masses.get(frame.singleton("0085"), 0.0)
        assert abs(tin_mass - 0.5) < 1e-9

    def test_word_overlap_match(self):
        frame, cs = _make_frame()
        # "customer_email_address" contains "email address" words
        ba = name_match_to_mass("customer_email_address", frame, cs)
        assert ba.is_valid
        email_mass = ba.masses.get(frame.singleton("0076"), 0.0)
        assert abs(email_mass - 0.3) < 1e-9

    def test_no_match_returns_vacuous(self):
        frame, cs = _make_frame()
        ba = name_match_to_mass("xyzzy_nonsense", frame, cs)
        assert ba.is_valid
        assert ba.masses[frame.theta] == 1.0
