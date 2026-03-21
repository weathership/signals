"""Classifier Protocol and Classification result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sigint.category_set import ReferenceCategory
from sigint.ontology import Category
from sigint.sampler import ColumnSample


@dataclass(frozen=True)
class Classification:
    """Result of classifying a single column."""

    category: Category | ReferenceCategory
    confidence: float
    evidence: str
    sensitivity_code: str | None = None
    boost: float = 0.0  # non-embedding score added (track as negative metric)

    @property
    def atlas_type_name(self) -> str:
        return self.category.atlas_type_name


class Classifier(Protocol):
    """Interface for column classifiers.

    Implementations must provide a ``classify`` method that inspects a
    ``ColumnSample`` and returns a ``Classification`` or ``None``.
    """

    def classify(
        self,
        sample: ColumnSample,
        siblings: list[ColumnSample] | None = None,
    ) -> Classification | None: ...


@dataclass(frozen=True)
class HierarchicalClassification:
    """Classification with Dempster-Shafer belief intervals.

    Extends Classification fields for backward compatibility, adding
    DST fields for uncertainty-aware downstream consumption.
    """

    # Backward-compat fields (same as Classification)
    category: Category | ReferenceCategory
    confidence: float
    evidence: str
    sensitivity_code: str | None = None
    boost: float = 0.0

    # DST fields
    belief_assignment: object = None  # BeliefAssignment (avoid import cycle at module level)
    conflict: float = 0.0
    source_masses: dict[str, object] = field(default_factory=dict)  # name → BeliefAssignment

    # Store references for hierarchy navigation (not serialized)
    _frame: object = field(default=None, repr=False, compare=False)
    _category_set: object = field(default=None, repr=False, compare=False)

    @property
    def atlas_type_name(self) -> str:
        return self.category.atlas_type_name

    def belief_at(self, code: str) -> float:
        """Bel(code) — belief that the column is this specific category."""
        from sigint.belief import FocalElement
        if self.belief_assignment is None:
            return 0.0
        if self._frame is not None:
            # Try singleton first
            singletons = self._frame.singletons
            if code in singletons:
                return self.belief_assignment.belief(singletons[code])
            internal = self._frame.internal_nodes
            if code in internal:
                return self.belief_assignment.belief(internal[code])
        # Fallback: construct a focal element
        if self._category_set is not None and hasattr(self._category_set, "descendants"):
            desc = self._category_set.descendants(code)
            fe = FocalElement(desc)
        else:
            fe = FocalElement(frozenset({code}))
        return self.belief_assignment.belief(fe)

    def plausibility_at(self, code: str) -> float:
        """Pl(code) — plausibility that the column is this category."""
        from sigint.belief import FocalElement
        if self.belief_assignment is None:
            return 0.0
        if self._frame is not None:
            singletons = self._frame.singletons
            if code in singletons:
                return self.belief_assignment.plausibility(singletons[code])
            internal = self._frame.internal_nodes
            if code in internal:
                return self.belief_assignment.plausibility(internal[code])
        if self._category_set is not None and hasattr(self._category_set, "descendants"):
            desc = self._category_set.descendants(code)
            fe = FocalElement(desc)
        else:
            fe = FocalElement(frozenset({code}))
        return self.belief_assignment.plausibility(fe)

    def interval_at(self, code: str) -> tuple[float, float]:
        """Return (Bel, Pl) at code."""
        return (self.belief_at(code), self.plausibility_at(code))

    @property
    def uncertainty_gap(self) -> float:
        """Pl - Bel for the predicted category."""
        if self.belief_assignment is None or self._frame is None:
            return 0.0
        code = self.category.code
        return self.plausibility_at(code) - self.belief_at(code)

    @property
    def needs_clarification(self) -> bool:
        """True when uncertainty gap > 0.3 or conflict > 0.2."""
        return self.uncertainty_gap > 0.3 or self.conflict > 0.2

    @classmethod
    def from_combined_evidence(
        cls,
        source_masses: dict[str, object],  # name → BeliefAssignment
        frame,  # FrameOfDiscernment
        category_set,  # HierarchicalCategorySet
        sensitivity_code: str | None = None,
    ) -> HierarchicalClassification:
        """Combine source masses via Dempster's rule, find best category.

        Args:
            source_masses: Named evidence sources, each a BeliefAssignment.
            frame: The frame of discernment.
            category_set: For hierarchy navigation and label lookup.
            sensitivity_code: Optional sensitivity code for the result.
        """
        from sigint.belief import BeliefAssignment, combine_multiple

        # Filter out vacuous sources (they don't contribute)
        non_vacuous = []
        for name, ba in source_masses.items():
            if len(ba.masses) > 1 or (len(ba.masses) == 1 and frame.theta not in ba.masses):
                non_vacuous.append(ba)

        if not non_vacuous:
            # All vacuous — pick best from first non-vacuous or return None
            combined = frame.vacuous()
            conflict = 0.0
        else:
            try:
                combined = combine_multiple(non_vacuous)
                # Compute conflict K from the last combination
                # (approximate: product of all pairwise conflicts)
                conflict = _compute_conflict(non_vacuous)
            except ValueError:
                combined = frame.vacuous()
                conflict = 1.0

        # Find best category via pignistic probability
        best_code = None
        best_betp = -1.0
        for code, singleton in frame.singletons.items():
            betp = combined.pignistic_probability(singleton)
            if betp > best_betp:
                best_betp = betp
                best_code = code

        if best_code is None:
            # Should not happen with a non-empty frame
            raise ValueError("No singletons in frame")

        cat = category_set.by_code.get(best_code)
        if cat is None:
            cat = category_set.all_by_code.get(best_code)

        # Build evidence string
        source_parts = []
        for name, ba in source_masses.items():
            # Get the best singleton mass as a summary
            best_mass = 0.0
            for fe, m in ba.masses.items():
                if len(fe.codes) == 1 and m > best_mass:
                    best_mass = m
            source_parts.append(f"{name}={best_mass:.3f}")

        bel = combined.belief(frame.singleton(best_code))
        pl = combined.plausibility(frame.singleton(best_code))
        evidence = (
            f"dst({', '.join(source_parts)}) → {cat.label} "
            f"[Bel={bel:.2f}, Pl={pl:.2f}, K={conflict:.2f}]"
        )

        return cls(
            category=cat,
            confidence=round(best_betp, 3),
            evidence=evidence,
            sensitivity_code=sensitivity_code,
            boost=0.0,
            belief_assignment=combined,
            conflict=round(conflict, 4),
            source_masses=source_masses,
            _frame=frame,
            _category_set=category_set,
        )


def _compute_conflict(assignments: list) -> float:
    """Approximate conflict K from pairwise combination."""
    if len(assignments) < 2:
        return 0.0

    total_conflict = 0.0
    result = assignments[0]
    for other in assignments[1:]:
        # Compute conflict for this pair
        pair_conflict = 0.0
        for fe1, m1 in result.masses.items():
            for fe2, m2 in other.masses.items():
                if not (fe1.codes & fe2.codes):
                    pair_conflict += m1 * m2
        total_conflict = max(total_conflict, pair_conflict)

        from sigint.belief import dempster_combine
        try:
            result = dempster_combine(result, other)
        except ValueError:
            return 1.0

    return total_conflict
