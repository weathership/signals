"""Step definitions for evidence_fusion.feature."""

from behave import given, then, when


def _build_frame(context):
    """Build and cache the SIGDG frame of discernment on context."""
    if hasattr(context, "frame"):
        return
    from sigint.belief import FrameOfDiscernment
    from sigint.category_set import sigdg_category_set
    from sigint.confusable_pairs import get_confusable_pairs

    cs = sigdg_category_set(hierarchical=True)
    pairs = get_confusable_pairs("sigdg")
    context.category_set_hier = cs
    context.frame = FrameOfDiscernment(cs, confusable_pairs=pairs)


@given("the SIGDG frame of discernment")
def step_sigdg_frame(context):
    _build_frame(context)


@given("cosine similarities across leaf categories")
def step_cosine_similarities(context):
    _build_frame(context)
    # Build fake similarities: give EmailAddress high sim, rest low
    context.similarities = {}
    for code in context.category_set_hier.leaf_codes:
        context.similarities[code] = 0.1
    context.similarities["0076"] = 0.9  # EmailAddress


@when("I convert cosine similarities to a mass function with discount {discount:g}")
def step_cosine_to_mass(context, discount):
    from sigint.mass_functions import cosine_to_mass

    context.mass = cosine_to_mass(
        context.similarities, context.frame, discount=discount,
    )


@then("the mass function is valid")
def step_mass_valid(context):
    assert context.mass.is_valid, (
        f"Mass function is not valid. Masses sum to "
        f"{sum(context.mass.masses.values()):.6f}"
    )


@then("the Theta focal element has mass approximately {expected:g}")
def step_theta_mass(context, expected):
    theta = context.frame.theta
    theta_mass = context.mass.masses.get(theta, 0.0)
    assert abs(theta_mass - expected) < 0.15, (
        f"Expected Theta mass ~{expected}, got {theta_mass:.4f}"
    )


@when('I convert pattern signals ["{pattern}"] to a mass function')
def step_pattern_to_mass(context, pattern):
    from sigint.mass_functions import get_pattern_category_map, pattern_to_mass

    pcm = get_pattern_category_map("sigdg")
    context.mass = pattern_to_mass([pattern], context.frame, pattern_category_map=pcm)


@then("the EmailAddress singleton has the highest mass")
def step_email_highest(context):
    ea = context.frame.singleton("0076")
    ea_mass = context.mass.masses.get(ea, 0.0)
    for fe, m in context.mass.masses.items():
        if fe != context.frame.theta and fe != ea:
            assert ea_mass >= m, (
                f"EmailAddress mass ({ea_mass:.4f}) not highest — "
                f"{fe} has {m:.4f}"
            )


@given("the SIGDG frame of discernment and category set")
def step_sigdg_frame_and_cs(context):
    _build_frame(context)


@when('I evaluate name match for column "{name}"')
def step_name_match(context, name):
    from sigint.mass_functions import name_match_to_mass

    context.mass = name_match_to_mass(
        name, context.frame, context.category_set_hier,
    )


@then("the EmailAddress singleton has non-zero mass")
def step_email_nonzero(context):
    ea = context.frame.singleton("0076")
    ea_mass = context.mass.masses.get(ea, 0.0)
    assert ea_mass > 0, f"Expected non-zero mass for EmailAddress, got {ea_mass}"


# ── Combination ──────────────────────────────────────────────────────

@given("two independent mass functions over the SIGDG frame")
def step_two_masses(context):
    from sigint.mass_functions import cosine_to_mass, name_match_to_mass

    _build_frame(context)
    sims = {code: 0.1 for code in context.category_set_hier.leaf_codes}
    sims["0076"] = 0.85
    context.m1 = cosine_to_mass(sims, context.frame, discount=0.3)
    context.m2 = name_match_to_mass(
        "email_address", context.frame, context.category_set_hier,
    )


@when("I combine them using Dempster's rule")
def step_dempster_combine(context):
    from sigint.belief import dempster_combine

    context.combined, context.conflict_k = dempster_combine(context.m1, context.m2)


@then("the combined assignment is valid")
def step_combined_valid(context):
    assert context.combined.is_valid, "Combined assignment is not valid"


@then("the conflict K is between 0 and 1")
def step_conflict_range(context):
    assert 0 <= context.conflict_k <= 1, (
        f"Expected 0 <= K <= 1, got {context.conflict_k}"
    )


@then("belief <= plausibility for every singleton")
def step_bel_le_pl(context):
    for code in context.category_set_hier.leaf_codes:
        fe = context.frame.singleton(code)
        bel = context.combined.belief(fe)
        pl = context.combined.plausibility(fe)
        assert bel <= pl + 1e-9, (
            f"Code {code}: belief ({bel}) > plausibility ({pl})"
        )


# ── Multiple combination ─────────────────────────────────────────────

@given("mass functions from cosine, pattern, and name-match sources")
def step_three_masses(context):
    from sigint.mass_functions import (
        cosine_to_mass,
        get_pattern_category_map,
        name_match_to_mass,
        pattern_to_mass,
    )

    _build_frame(context)
    sims = {code: 0.1 for code in context.category_set_hier.leaf_codes}
    sims["0076"] = 0.85
    context.mass_list = [
        cosine_to_mass(sims, context.frame, discount=0.3),
        pattern_to_mass(
            ["email_pattern"], context.frame,
            pattern_category_map=get_pattern_category_map("sigdg"),
        ),
        name_match_to_mass(
            "email_address", context.frame, context.category_set_hier,
        ),
    ]


@when("I combine all three using combine_multiple")
def step_combine_multiple(context):
    from sigint.belief import combine_multiple

    context.combined, context.conflict_k = combine_multiple(context.mass_list)


# ── Confusable pairs ─────────────────────────────────────────────────

@given("the SIGDG frame with confusable pairs")
def step_frame_with_confusables(context):
    _build_frame(context)


@then("the frame has at least one confusable pair focal element")
def step_has_confusable(context):
    assert len(context.frame.confusables) >= 1, (
        f"Expected at least 1 confusable pair, got {len(context.frame.confusables)}"
    )


# ── Vacuous mass ─────────────────────────────────────────────────────

@when("I create a vacuous mass function")
def step_vacuous(context):
    context.mass = context.frame.vacuous()


@then("all mass is on Theta")
def step_all_on_theta(context):
    theta = context.frame.theta
    theta_mass = context.mass.masses.get(theta, 0.0)
    assert abs(theta_mass - 1.0) < 1e-9, (
        f"Expected Theta mass = 1.0, got {theta_mass}"
    )


@then("belief for any singleton is 0")
def step_singleton_bel_zero(context):
    for code in list(context.category_set_hier.leaf_codes)[:5]:
        fe = context.frame.singleton(code)
        bel = context.mass.belief(fe)
        assert abs(bel) < 1e-9, (
            f"Expected belief=0 for {code}, got {bel}"
        )
