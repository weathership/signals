"""Step definitions for embedding_classification.feature."""

from behave import given, then, when

from features.classification.steps.helpers import make_classifier, make_sample


@given("an EmbeddingClassifier with the SIGDG taxonomy")
def step_sigdg_classifier(context):
    from sigint.category_set import sigdg_category_set

    cs = sigdg_category_set(hierarchical=True)
    context.classifier = make_classifier(category_set=cs)
    context.category_set = cs


@given("an EmbeddingClassifier with no model_path")
def step_classifier_no_model(context):
    from sigint.category_set import sigdg_category_set

    cs = sigdg_category_set(hierarchical=True)
    context.classifier = make_classifier(category_set=cs)
    context.category_set = cs


@when('I classify a column "{name}" with values:')
def step_classify_column(context, name):
    values = [row["value"] for row in context.table]
    sample = make_sample(name, values=values)
    context.classification = context.classifier.classify(sample)


@then("the classification is not None")
def step_not_none(context):
    assert context.classification is not None, "Classification result is None"


@then("the classification has a belief assignment")
def step_has_belief(context):
    assert context.classification.belief_assignment is not None, (
        "Classification has no belief assignment"
    )


@then("the confidence is above {threshold:g}")
def step_confidence_above(context, threshold):
    assert context.classification.confidence >= threshold, (
        f"Confidence {context.classification.confidence} < {threshold}"
    )


# ── Belief interval accessors ────────────────────────────────────────

@given("a classification result exists on context")
def step_ensure_classification(context):
    if hasattr(context, "classification") and context.classification is not None:
        return
    # Create one
    from sigint.category_set import sigdg_category_set

    cs = sigdg_category_set(hierarchical=True)
    clf = make_classifier(category_set=cs)
    sample = make_sample("ssn", values=["123-45-6789", "987-65-4321"])
    context.classification = clf.classify(sample)
    context.category_set = cs
    assert context.classification is not None


@then("belief_at returns a value between 0 and 1")
def step_belief_at_range(context):
    code = context.classification.category.code
    bel = context.classification.belief_at(code)
    assert 0 <= bel <= 1, f"belief_at({code}) = {bel}, not in [0,1]"


@then("plausibility_at >= belief_at for the predicted code")
def step_pl_ge_bel(context):
    code = context.classification.category.code
    bel = context.classification.belief_at(code)
    pl = context.classification.plausibility_at(code)
    assert pl >= bel - 1e-9, (
        f"plausibility ({pl}) < belief ({bel}) for {code}"
    )


@then("uncertainty_gap equals plausibility minus belief")
def step_uncertainty_gap(context):
    code = context.classification.category.code
    bel = context.classification.belief_at(code)
    pl = context.classification.plausibility_at(code)
    gap = context.classification.uncertainty_gap
    expected = pl - bel
    assert abs(gap - expected) < 1e-6, (
        f"uncertainty_gap ({gap}) != Pl-Bel ({expected})"
    )


# ── Source masses ────────────────────────────────────────────────────

@then('source_masses contains "{source}"')
def step_source_mass_key(context, source):
    assert source in context.classification.source_masses, (
        f"Expected '{source}' in source_masses, "
        f"got keys: {list(context.classification.source_masses.keys())}"
    )
