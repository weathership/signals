"""Tests for evidence-to-mass converters."""

from __future__ import annotations

from sigint.belief import FrameOfDiscernment
from sigint.category_set import sigdg_category_set
from sigint.mass_functions import (
    catboost_to_mass,
    cosine_to_mass,
    name_match_to_mass,
    pattern_to_mass,
    svm_to_mass,
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


    def test_mismatched_classes_still_valid(self):
        """CatBoost proba with unknown codes still produces valid mass (R-04)."""
        frame, _ = _make_frame()
        proba = {"0085": 0.8, "0076": 0.1, "UNKNOWN": 0.1}
        ba = catboost_to_mass(proba, frame)
        assert ba.is_valid
        # Residual from UNKNOWN should go to Theta
        assert ba.masses[frame.theta] > 0.15  # base discount + residual

    def test_all_unknown_classes_returns_near_vacuous(self):
        """All proba codes unknown → all evidence mass to Theta."""
        frame, _ = _make_frame()
        proba = {"UNKNOWN_A": 0.6, "UNKNOWN_B": 0.4}
        ba = catboost_to_mass(proba, frame)
        assert ba.is_valid
        assert abs(ba.masses[frame.theta] - 1.0) < 1e-9


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


class TestSvmToMass:
    def test_high_probability_concentrated(self):
        """High SVM probability → concentrated mass on singleton."""
        frame, _ = _make_frame()
        proba = {"0085": 0.85, "0076": 0.10, "0074": 0.05}
        ba = svm_to_mass(proba, frame, discount=0.20)
        assert ba.is_valid
        tin_mass = ba.masses.get(frame.singleton("0085"), 0.0)
        assert tin_mass > 0.5

    def test_empty_returns_vacuous(self):
        frame, _ = _make_frame()
        ba = svm_to_mass({}, frame)
        assert ba.is_valid
        assert ba.masses[frame.theta] == 1.0

    def test_discount_controls_theta(self):
        frame, _ = _make_frame()
        proba = {"0085": 0.9, "0076": 0.1}
        ba = svm_to_mass(proba, frame, discount=0.4)
        assert abs(ba.masses[frame.theta] - 0.4) < 1e-9

    def test_default_discount_is_020(self):
        """Default SVM discount (0.20) is lower than cosine (0.30)."""
        frame, _ = _make_frame()
        proba = {"0085": 1.0}
        ba = svm_to_mass(proba, frame)
        assert abs(ba.masses[frame.theta] - 0.20) < 1e-9

    def test_mismatched_classes_still_valid(self):
        """SVM proba with unknown codes still produces valid mass (R-04)."""
        frame, _ = _make_frame()
        proba = {"0085": 0.7, "UNKNOWN": 0.3}
        ba = svm_to_mass(proba, frame, discount=0.20)
        assert ba.is_valid
        # Residual from UNKNOWN should go to Theta
        assert ba.masses[frame.theta] > 0.20

    def test_probabilities_scaled_by_evidence_mass(self):
        """SVM probabilities are scaled by (1 - discount)."""
        frame, _ = _make_frame()
        proba = {"0085": 0.6, "0076": 0.4}
        ba = svm_to_mass(proba, frame, discount=0.20)
        assert ba.is_valid
        tin_mass = ba.masses.get(frame.singleton("0085"), 0.0)
        email_mass = ba.masses.get(frame.singleton("0076"), 0.0)
        assert abs(tin_mass - 0.6 * 0.8) < 1e-9
        assert abs(email_mass - 0.4 * 0.8) < 1e-9


def _make_frame_with_pairs():
    cs = sigdg_category_set(hierarchical=True)
    pairs = [("0013", "0012")]  # DeviceIdentifier / PlatformIdentifier
    frame = FrameOfDiscernment(cs, confusable_pairs=pairs)
    return frame, cs


class TestConfusableRedistribution:
    def test_cosine_ambiguous_pair_redistributes(self):
        """Top-2 in a confusable pair with close ratio → mass on pair FE."""
        frame, _ = _make_frame_with_pairs()
        # Give similar similarities to the confusable pair members
        sims = {"0013": 0.9, "0012": 0.85}
        ba = cosine_to_mass(sims, frame, discount=0.3)
        assert ba.is_valid

        # The pair focal element should have received some mass
        pair_fe = frame.confusables[0]
        pair_mass = ba.masses.get(pair_fe, 0.0)
        assert pair_mass > 0, "Expected mass on confusable pair FE"

    def test_cosine_clear_winner_no_redistribution(self):
        """Dominant singleton → no redistribution to pair FE."""
        frame, _ = _make_frame_with_pairs()
        # Wide gap: after softmax, ratio will be ~7:1 (well above 3:1 threshold)
        sims = {"0013": 0.95, "0012": -1.0}
        ba = cosine_to_mass(sims, frame, discount=0.3)
        assert ba.is_valid

        pair_fe = frame.confusables[0]
        pair_mass = ba.masses.get(pair_fe, 0.0)
        assert pair_mass == 0.0, "No mass expected on pair FE for clear winner"

    def test_catboost_ambiguous_pair_redistributes(self):
        """CatBoost with ambiguous pair → mass on pair FE."""
        frame, _ = _make_frame_with_pairs()
        proba = {"0013": 0.45, "0012": 0.40, "0085": 0.15}
        ba = catboost_to_mass(proba, frame)
        assert ba.is_valid

        pair_fe = frame.confusables[0]
        pair_mass = ba.masses.get(pair_fe, 0.0)
        assert pair_mass > 0, "Expected mass on confusable pair FE"

    def test_no_redistribution_without_pairs(self):
        """Frame without confusable pairs → no redistribution."""
        frame, _ = _make_frame()  # no pairs
        sims = {"0013": 0.9, "0012": 0.85}
        ba = cosine_to_mass(sims, frame, discount=0.3)
        assert ba.is_valid

        # No pair focal elements exist, so no pair mass
        for fe in ba.masses:
            assert len(fe.codes) != 2 or fe == frame.theta or ba.masses[fe] == 0.0

    def test_pignistic_with_pair_mass(self):
        """BetP distributes pair mass equally to both members."""
        from sigint.belief import BeliefAssignment, FocalElement

        a = FocalElement(frozenset({"A"}), "A")
        b = FocalElement(frozenset({"B"}), "B")
        pair_ab = FocalElement(frozenset({"A", "B"}), "A|B")
        theta = FocalElement(frozenset({"A", "B", "C"}), "Θ")

        # m({A})=0.3, m({A,B})=0.2, m(Θ)=0.5
        ba = BeliefAssignment(masses={a: 0.3, pair_ab: 0.2, theta: 0.5})
        assert ba.is_valid

        # BetP({A}) = 0.3/1 + 0.2/2 + 0.5/3 = 0.3 + 0.1 + 0.1667 = 0.5667
        betp_a = ba.pignistic_probability(a)
        assert abs(betp_a - (0.3 + 0.1 + 0.5 / 3)) < 1e-9

        # BetP({B}) = 0.2/2 + 0.5/3 = 0.1 + 0.1667 = 0.2667
        betp_b = ba.pignistic_probability(b)
        assert abs(betp_b - (0.1 + 0.5 / 3)) < 1e-9

        # Pair mass splits equally: A gets more total BetP than B
        assert betp_a > betp_b
