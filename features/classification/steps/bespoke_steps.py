"""Step definitions for bespoke_dataset.feature."""

from behave import given, then, when

from features.classification.steps.helpers import (
    make_classifier,
    make_sample,
    make_temp_annotations_csv,
    make_temp_vocab_mapping,
    register_temp_file,
)

# Minimal annotation categories for BDD testing
_BESPOKE_CATEGORIES = [
    {
        "code": "1.1.1.1",
        "label": "CreditCardNumber",
        "definition": "Primary account number on a payment card",
        "common_names": "credit_card,cc_number,pan",
    },
    {
        "code": "1.1.1.2",
        "label": "SocialSecurityNumber",
        "definition": "US Social Security Number",
        "common_names": "ssn,social_security",
    },
    {
        "code": "1.1.2.1",
        "label": "EmailAddress",
        "definition": "Electronic mail address",
        "common_names": "email,email_addr",
    },
    {
        "code": "1.1.2.2",
        "label": "PhoneNumber",
        "definition": "Telephone number",
        "common_names": "phone,tel,phone_number",
    },
    {
        "code": "1.1.3.1",
        "label": "FullName",
        "definition": "Full legal name of a person",
        "common_names": "full_name,name,person_name",
    },
]


@given("an annotations CSV with known leaf categories")
def step_annotations_csv(context):
    path = make_temp_annotations_csv(_BESPOKE_CATEGORIES)
    register_temp_file(context, path)
    context.annotations_path = path


@when("I build a category set from the annotations CSV")
def step_build_from_csv(context):
    from sigint.category_set import annotation_category_set

    context.bespoke_cs = annotation_category_set(
        context.annotations_path, hierarchical=False,
    )


@then('the category set has "{name}" as its name')
def step_cs_name(context, name):
    assert context.bespoke_cs.name == name, (
        f"Expected name={name!r}, got {context.bespoke_cs.name!r}"
    )


@then("the category set contains leaf categories from the CSV")
def step_cs_has_leaves(context):
    assert len(context.bespoke_cs.categories) > 0, "No categories loaded"


@then("each category has embedding text derived from its label")
def step_cs_embedding_text(context):
    for cat in context.bespoke_cs.categories:
        assert cat.embedding_text, (
            f"Category {cat.code} ({cat.label}) has empty embedding_text"
        )


# ── Hierarchical ─────────────────────────────────────────────────────

@when("I build a hierarchical category set from the annotations CSV")
def step_build_hierarchical(context):
    from sigint.category_set import annotation_category_set

    context.bespoke_cs = annotation_category_set(
        context.annotations_path, hierarchical=True,
    )


@then("the category set has parent-child relationships")
def step_has_hierarchy(context):
    from sigint.category_set import HierarchicalCategorySet

    assert isinstance(context.bespoke_cs, HierarchicalCategorySet), (
        f"Expected HierarchicalCategorySet, got {type(context.bespoke_cs)}"
    )
    assert len(context.bespoke_cs.children) > 0, "No parent-child relationships"


@then("leaf codes are present in the leaf_codes set")
def step_leaf_codes_present(context):
    for cat in context.bespoke_cs.categories:
        assert cat.code in context.bespoke_cs.leaf_codes, (
            f"Leaf {cat.code} not in leaf_codes"
        )


# ── Classification with bespoke taxonomy ─────────────────────────────

@given("a hierarchical annotations category set is built")
def step_build_bespoke_hier(context):
    if not hasattr(context, "annotations_path"):
        path = make_temp_annotations_csv(_BESPOKE_CATEGORIES)
        register_temp_file(context, path)
        context.annotations_path = path

    from sigint.category_set import annotation_category_set

    context.bespoke_cs = annotation_category_set(
        context.annotations_path, hierarchical=True,
    )


@given("an EmbeddingClassifier is configured for the annotations taxonomy")
def step_bespoke_classifier(context):
    context.bespoke_clf = make_classifier(category_set=context.bespoke_cs)


@when('I classify a bespoke column "{name}" with values:')
def step_classify_bespoke(context, name):
    values = [row["value"] for row in context.table]
    sample = make_sample(name, values=values)
    context.bespoke_classification = context.bespoke_clf.classify(sample)


@then("the bespoke classification result is not None")
def step_bespoke_not_none(context):
    assert context.bespoke_classification is not None, (
        "Bespoke classification is None"
    )


@then("the bespoke classification has a belief assignment")
def step_bespoke_has_belief(context):
    assert context.bespoke_classification.belief_assignment is not None, (
        "Bespoke classification has no belief assignment"
    )


# ── Config switching ─────────────────────────────────────────────────

@when('I load config with taxonomy_name = "{name}"')
def step_load_config_taxonomy(context, name):
    from sigint.config import load_config

    context.cfg = load_config(overrides={"taxonomy_name": name})


@when('I load config with taxonomy_name = "annotations" and an annotations path')
def step_load_config_annotations(context):
    from sigint.config import load_config

    if not hasattr(context, "annotations_path"):
        path = make_temp_annotations_csv(_BESPOKE_CATEGORIES)
        register_temp_file(context, path)
        context.annotations_path = path

    context.cfg = load_config(overrides={
        "taxonomy_name": "annotations",
        "annotations_path": context.annotations_path,
    })


@when("I build a category set from the config")
def step_build_from_config(context):
    context.category_set = context.cfg.build_category_set()


# ── Evidence fusion with bespoke taxonomy ────────────────────────────

@given("a FrameOfDiscernment is built from the annotations category set")
def step_bespoke_frame(context):
    from sigint.belief import FrameOfDiscernment

    context.bespoke_frame = FrameOfDiscernment(context.bespoke_cs)


@when("I create evidence masses from cosine and name-match sources")
def step_bespoke_evidence(context):
    from sigint.mass_functions import cosine_to_mass, name_match_to_mass

    sims = {code: 0.1 for code in context.bespoke_cs.leaf_codes}
    # Give one category high similarity
    first_leaf = next(iter(context.bespoke_cs.leaf_codes))
    sims[first_leaf] = 0.85

    context.bespoke_m1 = cosine_to_mass(
        sims, context.bespoke_frame, discount=0.3,
    )
    context.bespoke_m2 = name_match_to_mass(
        "credit_card_number", context.bespoke_frame, context.bespoke_cs,
    )


@when("I combine bespoke evidence using Dempster's rule")
def step_bespoke_combine(context):
    from sigint.belief import dempster_combine

    context.bespoke_combined, context.bespoke_k = dempster_combine(
        context.bespoke_m1, context.bespoke_m2,
    )


@then("the combined bespoke assignment is valid")
def step_bespoke_combined_valid(context):
    assert context.bespoke_combined.is_valid, (
        "Combined bespoke assignment is not valid"
    )


@then("bespoke conflict K is between 0 and 1")
def step_bespoke_conflict(context):
    assert 0 <= context.bespoke_k <= 1, (
        f"Expected 0 <= K <= 1, got {context.bespoke_k}"
    )


# ── Vocabulary mapping in bespoke context ────────────────────────────

@given("a vocabulary mapping for the bespoke taxonomy")
def step_bespoke_vocab(context):
    entries = [
        ("Credit Card Number", "1.1.1.1"),
        ("PAN", "1.1.1.1"),
        ("Social Security Number", "1.1.1.2"),
    ]
    path = make_temp_vocab_mapping(entries)
    register_temp_file(context, path)

    from sigint.vocab_mapping import VocabMapping

    context.bespoke_vocab = VocabMapping.from_file(path)


@when("I resolve a known user label")
def step_resolve_known(context):
    context.bespoke_resolved = context.bespoke_vocab.resolve("PAN")


@then("the label maps to the expected taxonomy code")
def step_resolved_expected(context):
    assert context.bespoke_resolved == "1.1.1.1", (
        f"Expected '1.1.1.1', got {context.bespoke_resolved!r}"
    )


@when("I resolve an unknown user label")
def step_resolve_unknown(context):
    context.bespoke_resolved = context.bespoke_vocab.resolve("Unknown")


@then("the result is None")
def step_bespoke_none(context):
    assert context.bespoke_resolved is None, (
        f"Expected None, got {context.bespoke_resolved!r}"
    )
