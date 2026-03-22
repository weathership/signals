"""Step definitions for feature_extraction.feature."""

from behave import given, then, when

from features.classification.steps.helpers import make_sample


@given('a column sample "{name}" of type "{col_type}" with values:')
def step_sample_with_values(context, name, col_type):
    values = [row["value"] for row in context.table]
    context.sample = make_sample(name, col_type=col_type, values=values)


@given('a column sample "{name}" of type "{col_type}" with {nulls:d} nulls out of {total:d}')
def step_sample_with_nulls(context, name, col_type, nulls, total):
    context.sample = make_sample(
        name, col_type=col_type, values=["active", "inactive"],
        null_count=nulls, total_count=total,
    )


@when("I extract features from the sample")
def step_extract_features(context):
    from sigint.features import extract_features

    context.features = extract_features(context.sample)


@then('the feature pattern_signals includes "{pattern}"')
def step_pattern_includes(context, pattern):
    assert pattern in context.features.pattern_signals, (
        f"Expected '{pattern}' in pattern_signals, "
        f"got {context.features.pattern_signals}"
    )


@then("cardinality is {expected:d}")
def step_cardinality(context, expected):
    assert context.features.cardinality == expected, (
        f"Expected cardinality={expected}, got {context.features.cardinality}"
    )


@then("avg_value_length is greater than {threshold:d}")
def step_avg_len_gt(context, threshold):
    assert context.features.avg_value_length > threshold, (
        f"Expected avg_value_length > {threshold}, "
        f"got {context.features.avg_value_length}"
    )


@then("null_ratio is {expected:g}")
def step_null_ratio(context, expected):
    assert abs(context.features.null_ratio - expected) < 1e-4, (
        f"Expected null_ratio={expected}, got {context.features.null_ratio}"
    )


# ── Feature ablation ──────────────────────────────────────────────────

@given("a column sample with extracted features")
def step_sample_with_features(context):
    from sigint.features import extract_features

    context.sample = make_sample(
        "email_address", values=["alice@example.com", "bob@test.org"],
    )
    context.features = extract_features(context.sample)


@when("I build embedding text with all features enabled")
def step_embedding_text_all(context):
    context.embedding_text = context.features.to_embedding_text()


@then("the embedding text contains the column name")
def step_text_has_name(context):
    assert "email" in context.embedding_text.lower(), (
        f"Expected column name in embedding text: {context.embedding_text}"
    )


@when('I build embedding text with "{feature}" disabled')
def step_embedding_text_masked(context, feature):
    mask = {feature: False}
    context.embedding_text = context.features.to_embedding_text(mask=mask)


@then("the embedding text does not contain sample values")
def step_text_no_values(context):
    # Sample values are comma-separated in the text
    assert "alice@example.com" not in context.embedding_text, (
        f"Expected no sample values in embedding text: {context.embedding_text}"
    )


# ── Sibling context ──────────────────────────────────────────────────

@given('a column sample "{name}" with siblings "{s1}", "{s2}", "{s3}"')
def step_sample_with_siblings(context, name, s1, s2, s3):
    context.sample = make_sample(name, values=["alice@example.com"])
    context.siblings = [
        make_sample(s1), make_sample(s2), make_sample(s3),
    ]


@when("I extract features with sibling context")
def step_extract_with_siblings(context):
    from sigint.features import extract_features

    context.features = extract_features(
        context.sample, siblings=context.siblings,
    )


@then('the sibling_context contains "{name}"')
def step_sibling_has(context, name):
    assert name in context.features.sibling_names, (
        f"Expected '{name}' in sibling_names, "
        f"got {context.features.sibling_names}"
    )
