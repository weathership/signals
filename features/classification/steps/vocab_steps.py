"""Step definitions for vocabulary_mapping.feature."""

from behave import given, then, when

from features.classification.steps.helpers import (
    make_temp_vocab_mapping,
    register_temp_file,
)


@given("a vocabulary mapping JSON file with entries:")
def step_vocab_json(context):
    entries = [(row["user_label"], row["code"]) for row in context.table]
    path = make_temp_vocab_mapping(entries)
    register_temp_file(context, path)
    context.vocab_path = path


@when("I load the VocabMapping from the file")
def step_load_vocab(context):
    from sigint.vocab_mapping import VocabMapping

    context.vocab = VocabMapping.from_file(context.vocab_path)


@then("the mapping contains {n:d} entries")
def step_mapping_count(context, n):
    assert len(context.vocab.mappings) == n, (
        f"Expected {n} entries, got {len(context.vocab.mappings)}"
    )


@given("a loaded VocabMapping")
def step_loaded_vocab(context):
    entries = [
        ("Credit Card Number", "0085"),
        ("PAN", "0085"),
        ("SSN", "0083"),
    ]
    path = make_temp_vocab_mapping(entries)
    register_temp_file(context, path)

    from sigint.vocab_mapping import VocabMapping

    context.vocab = VocabMapping.from_file(path)


@when('I resolve "{label}"')
def step_resolve_label(context, label):
    context.resolved_code = context.vocab.resolve(label)


@then('the resolved code is "{code}"')
def step_resolved_is(context, code):
    assert context.resolved_code == code, (
        f"Expected code={code!r}, got {context.resolved_code!r}"
    )


@then("the resolved code is None")
def step_resolved_none(context):
    assert context.resolved_code is None, (
        f"Expected None, got {context.resolved_code!r}"
    )
