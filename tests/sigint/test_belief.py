"""Tests for Dempster-Shafer belief functions."""

from __future__ import annotations

import pytest

from sigint.belief import (
    BeliefAssignment,
    FocalElement,
    FrameOfDiscernment,
    combine_multiple,
    dempster_combine,
)
from sigint.category_set import sigdg_category_set


# ── FocalElement ─────────────────────────────────────────────────────


class TestFocalElement:
    def test_equality(self):
        a = FocalElement(frozenset({"0085"}), label="TIN")
        b = FocalElement(frozenset({"0085"}), label="TaxIdentifier")
        assert a == b  # labels don't affect equality

    def test_hash_consistency(self):
        a = FocalElement(frozenset({"0085"}))
        b = FocalElement(frozenset({"0085"}))
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_repr(self):
        fe = FocalElement(frozenset({"0085"}), label="TIN")
        assert "TIN" in repr(fe)


# ── BeliefAssignment ─────────────────────────────────────────────────


class TestBeliefAssignment:
    def _make_simple(self):
        """A simple assignment: m({A})=0.6, m({B})=0.1, m(Θ)=0.3."""
        a = FocalElement(frozenset({"A"}), "A")
        b = FocalElement(frozenset({"B"}), "B")
        theta = FocalElement(frozenset({"A", "B", "C"}), "Θ")
        return BeliefAssignment(masses={a: 0.6, b: 0.1, theta: 0.3}), a, b, theta

    def test_validity(self):
        ba, _, _, _ = self._make_simple()
        assert ba.is_valid

    def test_invalid_when_not_summing(self):
        a = FocalElement(frozenset({"A"}))
        ba = BeliefAssignment(masses={a: 0.5})
        assert not ba.is_valid

    def test_normalization(self):
        a = FocalElement(frozenset({"A"}))
        b = FocalElement(frozenset({"B"}))
        ba = BeliefAssignment(masses={a: 2.0, b: 1.0})
        normalized = ba.normalize()
        assert normalized.is_valid
        assert abs(normalized.masses[a] - 2.0 / 3.0) < 1e-9

    def test_belief(self):
        ba, a, b, theta = self._make_simple()
        # Bel({A}) = m({A}) = 0.6 (only {A} ⊆ {A})
        assert abs(ba.belief(a) - 0.6) < 1e-9

    def test_plausibility(self):
        ba, a, b, theta = self._make_simple()
        # Pl({A}) = m({A}) + m(Θ) = 0.6 + 0.3 = 0.9
        assert abs(ba.plausibility(a) - 0.9) < 1e-9

    def test_belief_interval(self):
        ba, a, _, _ = self._make_simple()
        bel, pl = ba.belief_interval(a)
        assert bel <= pl

    def test_uncertainty(self):
        ba, a, _, _ = self._make_simple()
        gap = ba.uncertainty(a)
        assert abs(gap - 0.3) < 1e-9  # Pl - Bel = 0.9 - 0.6

    def test_pignistic_probability(self):
        ba, a, b, theta = self._make_simple()
        # BetP({A}) = m({A})/1 + m(Θ)/3 = 0.6 + 0.1 = 0.7
        betp_a = ba.pignistic_probability(a)
        assert abs(betp_a - 0.7) < 1e-9

    def test_pignistic_requires_singleton(self):
        ba, _, _, theta = self._make_simple()
        with pytest.raises(ValueError, match="singleton"):
            ba.pignistic_probability(theta)

    def test_belief_of_theta(self):
        ba, _, _, theta = self._make_simple()
        # Bel(Θ) = sum of all masses = 1.0
        assert abs(ba.belief(theta) - 1.0) < 1e-9


# ── Dempster combination ─────────────────────────────────────────────


class TestDempsterCombine:
    def test_agreeing_sources(self):
        """Two sources that agree on A strengthen belief."""
        a = FocalElement(frozenset({"A"}))
        theta = FocalElement(frozenset({"A", "B"}))

        m1 = BeliefAssignment(masses={a: 0.7, theta: 0.3})
        m2 = BeliefAssignment(masses={a: 0.6, theta: 0.4})

        result, k = dempster_combine(m1, m2)
        assert result.is_valid
        # Both agree on A, so belief in A should be higher
        assert result.belief(a) > 0.7
        # No conflict when both sources agree
        assert k == 0.0

    def test_conflicting_sources(self):
        """Two sources with partial conflict still combine."""
        a = FocalElement(frozenset({"A"}))
        b = FocalElement(frozenset({"B"}))
        theta = FocalElement(frozenset({"A", "B"}))

        m1 = BeliefAssignment(masses={a: 0.7, theta: 0.3})
        m2 = BeliefAssignment(masses={b: 0.6, theta: 0.4})

        result, k = dempster_combine(m1, m2)
        assert result.is_valid
        # K = m1({A})*m2({B}) = 0.7*0.6 = 0.42
        assert abs(k - 0.42) < 1e-9

    def test_total_conflict_raises(self):
        """Total conflict (K=1) raises ValueError."""
        a = FocalElement(frozenset({"A"}))
        b = FocalElement(frozenset({"B"}))

        m1 = BeliefAssignment(masses={a: 1.0})
        m2 = BeliefAssignment(masses={b: 1.0})

        with pytest.raises(ValueError, match="Total conflict"):
            dempster_combine(m1, m2)

    def test_vacuous_source(self):
        """Combining with vacuous (all Theta) preserves original."""
        a = FocalElement(frozenset({"A"}))
        theta = FocalElement(frozenset({"A", "B"}))

        m1 = BeliefAssignment(masses={a: 0.6, theta: 0.4})
        vacuous = BeliefAssignment(masses={theta: 1.0})

        result, k = dempster_combine(m1, vacuous)
        assert result.is_valid
        assert abs(result.belief(a) - 0.6) < 1e-9
        assert k == 0.0  # no conflict with vacuous

    def test_normalization_preserved(self):
        """Combined result is always normalized."""
        a = FocalElement(frozenset({"A"}))
        b = FocalElement(frozenset({"B"}))
        theta = FocalElement(frozenset({"A", "B"}))

        m1 = BeliefAssignment(masses={a: 0.5, theta: 0.5})
        m2 = BeliefAssignment(masses={b: 0.3, theta: 0.7})

        result, k = dempster_combine(m1, m2)
        assert result.is_valid
        assert k > 0  # partial conflict expected

    def test_returns_conflict_value(self):
        """dempster_combine returns the exact conflict K."""
        a = FocalElement(frozenset({"A"}))
        b = FocalElement(frozenset({"B"}))
        theta = FocalElement(frozenset({"A", "B"}))

        # m1({A})=0.5, m2({B})=0.3 → K = 0.5*0.3 = 0.15
        m1 = BeliefAssignment(masses={a: 0.5, theta: 0.5})
        m2 = BeliefAssignment(masses={b: 0.3, theta: 0.7})

        _, k = dempster_combine(m1, m2)
        assert abs(k - 0.15) < 1e-9

    def test_combine_multiple(self):
        """Three sources combine left-to-right."""
        a = FocalElement(frozenset({"A"}))
        theta = FocalElement(frozenset({"A", "B"}))

        m1 = BeliefAssignment(masses={a: 0.5, theta: 0.5})
        m2 = BeliefAssignment(masses={a: 0.4, theta: 0.6})
        m3 = BeliefAssignment(masses={a: 0.3, theta: 0.7})

        result, k = combine_multiple([m1, m2, m3])
        assert result.is_valid
        assert result.belief(a) > 0.5  # convergence strengthens belief
        assert k == 0.0  # all agree on A, no conflict

    def test_combine_multiple_cumulative_k(self):
        """Cumulative K uses Smarandache-Dezert formula: K = 1 - prod(1-Ki)."""
        a = FocalElement(frozenset({"A"}))
        b = FocalElement(frozenset({"B"}))
        theta = FocalElement(frozenset({"A", "B"}))

        m1 = BeliefAssignment(masses={a: 0.5, theta: 0.5})
        m2 = BeliefAssignment(masses={b: 0.3, theta: 0.7})
        m3 = BeliefAssignment(masses={b: 0.2, theta: 0.8})

        _, cumulative_k = combine_multiple([m1, m2, m3])
        # K should be > 0 (sources disagree)
        assert cumulative_k > 0
        # Cumulative K should be greater than any single pairwise K
        _, k12 = dempster_combine(m1, m2)
        assert cumulative_k > k12

    def test_combine_multiple_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            combine_multiple([])


# ── FrameOfDiscernment ───────────────────────────────────────────────


class TestFrameOfDiscernment:
    def test_sigdg_frame_size(self):
        """SIGDG frame has singletons for each leaf + internal nodes + theta."""
        cs = sigdg_category_set(hierarchical=True)
        frame = FrameOfDiscernment(cs)

        # Should have singleton for each leaf
        assert len(frame.singletons) == len(cs.categories)
        # Internal nodes exclude leaves
        assert len(frame.internal_nodes) > 0
        # Total focal elements: singletons + internal + theta (no confusables)
        expected = len(frame.singletons) + len(frame.internal_nodes) + 1
        assert len(frame.all_focal_elements) == expected

    def test_confusable_pairs(self):
        """Confusable pairs create additional focal elements."""
        cs = sigdg_category_set(hierarchical=True)
        pairs = [("0013", "0012")]  # DeviceIdentifier / PlatformIdentifier
        frame = FrameOfDiscernment(cs, confusable_pairs=pairs)

        assert len(frame.confusables) == 1
        pair_fe = frame.confusables[0]
        assert pair_fe.codes == frozenset({"0013", "0012"})

    def test_singleton_lookup(self):
        cs = sigdg_category_set(hierarchical=True)
        frame = FrameOfDiscernment(cs)

        tin = frame.singleton("0085")
        assert tin.codes == frozenset({"0085"})
        assert "TaxIdentifier" in tin.label

    def test_internal_lookup(self):
        cs = sigdg_category_set(hierarchical=True)
        frame = FrameOfDiscernment(cs)

        # IdentityInformation (0010) should be an internal node
        identity = frame.internal("0010")
        assert "0085" in identity.codes  # TaxIdentifier is a descendant
        assert "0012" in identity.codes  # PlatformIdentifier

    def test_theta_contains_all_leaves(self):
        cs = sigdg_category_set(hierarchical=True)
        frame = FrameOfDiscernment(cs)

        assert frame.theta.codes == cs.leaf_codes

    def test_confusable_map_lookup(self):
        """confusable_map maps each singleton code to pair FocalElements."""
        cs = sigdg_category_set(hierarchical=True)
        pairs = [("0013", "0012")]
        frame = FrameOfDiscernment(cs, confusable_pairs=pairs)

        cmap = frame.confusable_map
        assert "0013" in cmap
        assert "0012" in cmap
        # Both codes map to the same pair FocalElement
        assert cmap["0013"][0] is cmap["0012"][0]
        assert cmap["0013"][0].codes == frozenset({"0013", "0012"})

    def test_confusable_map_empty_without_pairs(self):
        cs = sigdg_category_set(hierarchical=True)
        frame = FrameOfDiscernment(cs)
        assert frame.confusable_map == {}

    def test_vacuous_mass(self):
        cs = sigdg_category_set(hierarchical=True)
        frame = FrameOfDiscernment(cs)

        vac = frame.vacuous()
        assert vac.is_valid
        assert vac.masses[frame.theta] == 1.0
