"""Evidence-to-mass converters for Dempster-Shafer belief functions.

Each converter transforms a specific evidence source into a BeliefAssignment
(mass function) compatible with Dempster's rule of combination.
"""

from __future__ import annotations

import math
import re

from sigint.belief import BeliefAssignment, FocalElement, FrameOfDiscernment


def _camel_to_words(name: str) -> str:
    """Split CamelCase into lowercase words."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()


def _redistribute_confusable_mass(
    masses: dict[FocalElement, float],
    frame: FrameOfDiscernment,
    ratio_threshold: float = 3.0,
) -> dict[FocalElement, float]:
    """Redistribute singleton mass to confusable pair focal elements.

    When the top-2 singleton masses (excluding Theta) both belong to a
    known confusable pair and their ratio is below *ratio_threshold*,
    half of the 2nd-place mass is moved to the pair focal element.

    This captures honest ambiguity: instead of arbitrarily picking one
    leaf, the mass function represents uncertainty between the pair.
    """
    if not frame.confusable_map:
        return masses

    # Find top-2 singletons by mass (exclude Theta)
    singleton_masses: list[tuple[str, FocalElement, float]] = []
    for fe, m in masses.items():
        if len(fe.codes) == 1:
            code = next(iter(fe.codes))
            singleton_masses.append((code, fe, m))

    singleton_masses.sort(key=lambda x: -x[2])
    if len(singleton_masses) < 2:
        return masses

    code1, _, m1 = singleton_masses[0]
    code2, fe2, m2 = singleton_masses[1]

    if m2 <= 1e-15:
        return masses

    # Check ratio — only redistribute when evidence is genuinely ambiguous
    ratio = m1 / m2
    if ratio >= ratio_threshold:
        return masses

    # Check if both codes share a confusable pair
    pairs1 = frame.confusable_map.get(code1, [])
    target_pair: FocalElement | None = None
    for pair_fe in pairs1:
        if code2 in pair_fe.codes:
            target_pair = pair_fe
            break

    if target_pair is None:
        return masses

    # Redistribute: move half of 2nd-place mass to the pair
    transfer = m2 / 2.0
    result = dict(masses)
    result[fe2] = m2 - transfer
    result[target_pair] = result.get(target_pair, 0.0) + transfer

    # Clean up near-zero entries
    return {fe: m for fe, m in result.items() if m > 1e-15}


def cosine_to_mass(
    similarities: dict[str, float],
    frame: FrameOfDiscernment,
    discount: float = 0.3,
) -> BeliefAssignment:
    """Convert cosine similarities to a mass function.

    Applies softmax to similarities, then discounts by *discount* so
    a fraction of mass goes to Theta (total ignorance).

    When the frame has confusable pairs and the top-2 singletons form
    a known pair with a close mass ratio, mass is redistributed to
    the pair focal element.

    Args:
        similarities: {category_code: cosine_similarity} for leaf codes.
        frame: The frame of discernment.
        discount: Fraction of total mass allocated to Theta.
    """
    if not similarities:
        return frame.vacuous()

    # Softmax with temperature=1
    max_sim = max(similarities.values())
    exp_sims = {
        code: math.exp(sim - max_sim)
        for code, sim in similarities.items()
        if code in frame.singletons
    }
    total_exp = sum(exp_sims.values())
    if total_exp <= 0:
        return frame.vacuous()

    masses: dict[FocalElement, float] = {}
    evidence_mass = 1.0 - discount
    for code, exp_val in exp_sims.items():
        prob = exp_val / total_exp
        mass = prob * evidence_mass
        if mass > 1e-15:
            masses[frame.singleton(code)] = mass

    masses[frame.theta] = discount
    masses = _redistribute_confusable_mass(masses, frame)
    return BeliefAssignment(masses=masses)


def catboost_to_mass(
    proba: dict[str, float],
    frame: FrameOfDiscernment,
    virtual_ensembles_variance: dict[str, float] | None = None,
) -> BeliefAssignment:
    """Convert CatBoost predicted probabilities to a mass function.

    When *virtual_ensembles_variance* is provided, high variance increases
    the discount (more mass to Theta).

    Args:
        proba: {category_code: probability} from predict_proba().
        frame: The frame of discernment.
        virtual_ensembles_variance: Optional per-class variance from
            CatBoost virtual ensembles.
    """
    if not proba:
        return frame.vacuous()

    # Compute discount from variance if available
    if virtual_ensembles_variance:
        avg_var = sum(virtual_ensembles_variance.values()) / len(virtual_ensembles_variance)
        # Map variance [0, 0.25] → discount [0.1, 0.5]
        discount = min(0.5, 0.1 + avg_var * 1.6)
    else:
        discount = 0.15  # CatBoost is generally well-calibrated

    masses: dict[FocalElement, float] = {}
    evidence_mass = 1.0 - discount
    for code, prob in proba.items():
        if code in frame.singletons and prob > 1e-15:
            masses[frame.singleton(code)] = prob * evidence_mass

    masses[frame.theta] = discount
    masses = _redistribute_confusable_mass(masses, frame)
    return BeliefAssignment(masses=masses)


# Pattern → SIGDG category code mapping
SIGDG_PATTERN_MAP: dict[str, str] = {
    "email_pattern": "0076",       # EmailAddress
    "phone_pattern": "0074",       # PhoneNumber
    "ssn_pattern": "0085",         # TaxIdentifier
    "ipv4_pattern": "0041",        # ConfigurationData
    "uuid_pattern": "0013",        # DeviceIdentifier
    "date_iso_pattern": "0077",    # AgeInformation
    "url_pattern": "0041",         # ConfigurationData
    "credit_card_pattern": "0070", # PaymentCardData
}


def get_pattern_category_map(taxonomy: str) -> dict[str, str]:
    """Return the pattern-to-category mapping for a given taxonomy."""
    if taxonomy == "gittables":
        from config.sigint.gittables_taxonomy import GITTABLES_PATTERN_MAP
        return GITTABLES_PATTERN_MAP
    return SIGDG_PATTERN_MAP


def pattern_to_mass(
    pattern_signals: list[str],
    frame: FrameOfDiscernment,
    pattern_category_map: dict[str, str] | None = None,
) -> BeliefAssignment:
    """Convert detected pattern signals to a mass function.

    Maps pattern names to category codes. When no patterns are detected,
    returns a vacuous mass function (all mass on Theta).

    Args:
        pattern_signals: List of detected pattern names (e.g., "email_pattern").
        frame: The frame of discernment.
        pattern_category_map: Optional override for pattern→code mapping.
    """
    if pattern_category_map is None:
        pattern_category_map = SIGDG_PATTERN_MAP

    if not pattern_signals:
        return frame.vacuous()

    # Collect all matched category codes
    matched_codes: set[str] = set()
    for pattern in pattern_signals:
        code = pattern_category_map.get(pattern)
        if code and code in frame.singletons:
            matched_codes.add(code)

    if not matched_codes:
        return frame.vacuous()

    # Distribute mass equally among matched codes
    mass_per_code = 0.9 / len(matched_codes)
    masses: dict[FocalElement, float] = {}
    for code in matched_codes:
        masses[frame.singleton(code)] = mass_per_code

    masses[frame.theta] = 0.1
    return BeliefAssignment(masses=masses)


def name_match_to_mass(
    column_name: str,
    frame: FrameOfDiscernment,
    category_set,
) -> BeliefAssignment:
    """Convert column name matching into a mass function.

    Replaces the additive boost hack with a proper evidence source.

    Matching levels:
    - Exact match: 0.7 singleton + 0.3 Theta
    - Abbreviation match: 0.5 singleton + 0.5 Theta
    - Word overlap match: 0.3 singleton + 0.7 Theta
    - No match: vacuous (1.0 Theta)

    Args:
        column_name: The column name to match.
        frame: The frame of discernment.
        category_set: CategorySet with label/abbrev for matching.
    """
    col_words = column_name.replace("_", " ").lower().strip()
    col_word_set = set(col_words.split())

    best_code: str | None = None
    best_mass = 0.0

    for cat in category_set.categories:
        if cat.code not in frame.singletons:
            continue

        cat_words = _camel_to_words(cat.label).replace("(", "").replace(")", "").strip()
        cat_abbrev = cat.abbrev.lower().strip()

        # Exact match
        if col_words == cat_words:
            if 0.7 > best_mass:
                best_code = cat.code
                best_mass = 0.7
        # Abbreviation match
        elif col_words.replace(" ", "") == cat_abbrev:
            if 0.5 > best_mass:
                best_code = cat.code
                best_mass = 0.5
        # Word overlap (multi-word categories only)
        else:
            cat_word_set = set(cat_words.split())
            if len(cat_word_set) > 1 and cat_word_set.issubset(col_word_set):
                if 0.3 > best_mass:
                    best_code = cat.code
                    best_mass = 0.3

    if best_code is None:
        return frame.vacuous()

    masses: dict[FocalElement, float] = {
        frame.singleton(best_code): best_mass,
        frame.theta: 1.0 - best_mass,
    }
    return BeliefAssignment(masses=masses)
