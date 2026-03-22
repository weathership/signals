"""Step definitions for taxonomy_management.feature."""

from behave import given, then, when


@when("I build the SIGDG category set with hierarchical = false")
def step_sigdg_flat(context):
    from sigint.category_set import sigdg_category_set

    context.category_set = sigdg_category_set(hierarchical=False)


@when("I build the SIGDG category set with hierarchical = true")
def step_sigdg_hierarchical(context):
    from sigint.category_set import sigdg_category_set

    context.category_set = sigdg_category_set(hierarchical=True)


@then("it contains {n:d} leaf categories")
def step_leaf_count(context, n):
    assert len(context.category_set.categories) == n, (
        f"Expected {n} leaf categories, got {len(context.category_set.categories)}"
    )


@then("each category has a code, label, and embedding_text")
def step_categories_have_fields(context):
    for cat in context.category_set.categories:
        assert cat.code, f"Category missing code: {cat}"
        assert cat.label, f"Category missing label: {cat}"
        assert cat.embedding_text, f"Category missing embedding_text: {cat}"


@then('the category set name is "{name}"')
def step_category_set_name(context, name):
    assert context.category_set.name == name, (
        f"Expected name={name!r}, got {context.category_set.name!r}"
    )


@then("it contains {n:d} leaf categories in the leaves")
def step_leaf_count_hierarchical(context, n):
    assert len(context.category_set.categories) == n, (
        f"Expected {n} leaf categories, got {len(context.category_set.categories)}"
    )


@then("all_categories includes parent nodes")
def step_all_categories_has_parents(context):
    from sigint.category_set import HierarchicalCategorySet

    assert isinstance(context.category_set, HierarchicalCategorySet)
    leaf_count = len(context.category_set.categories)
    all_count = len(context.category_set.all_categories)
    assert all_count > leaf_count, (
        f"Expected all_categories ({all_count}) > leaves ({leaf_count})"
    )


@then("leaf_codes returns a frozenset of {n:d} codes")
def step_leaf_codes_frozenset(context, n):
    lc = context.category_set.leaf_codes
    assert isinstance(lc, frozenset), f"Expected frozenset, got {type(lc)}"
    assert len(lc) == n, f"Expected {n} leaf codes, got {len(lc)}"


# ── Hierarchical navigation ──────────────────────────────────────────

@given("the SIGDG hierarchical category set is loaded")
def step_load_sigdg_hierarchical(context):
    from sigint.category_set import sigdg_category_set

    context.category_set = sigdg_category_set(hierarchical=True)


@then("descendants of a parent code include its leaf children")
def step_descendants(context):
    # Find a parent that has children
    for code, children in context.category_set.children.items():
        if children:
            descs = context.category_set.descendants(code)
            assert len(descs) > 0, (
                f"Parent {code} has children {children} but descendants() returned empty"
            )
            break
    else:
        raise AssertionError("No parent with children found")


@then("ancestors of a leaf code return the path to root")
def step_ancestors(context):
    leaf = next(iter(context.category_set.leaf_codes))
    ancestors = context.category_set.ancestors(leaf)
    # Should have at least one ancestor (the root or an intermediate node)
    assert len(ancestors) >= 1, (
        f"Expected at least 1 ancestor for leaf {leaf}, got {ancestors}"
    )


# ── Lookup ────────────────────────────────────────────────────────────

@given("the SIGDG category set is loaded")
def step_load_sigdg(context):
    from sigint.category_set import sigdg_category_set

    context.category_set = sigdg_category_set(hierarchical=False)


@when('I look up code "{code}"')
def step_lookup_code(context, code):
    context.looked_up = context.category_set.by_code.get(code)


@then('the category label is "{label}"')
def step_category_label(context, label):
    assert context.looked_up is not None, "No category found for code"
    assert context.looked_up.label == label, (
        f"Expected label={label!r}, got {context.looked_up.label!r}"
    )


@when('I look up abbreviation "{abbrev}"')
def step_lookup_abbrev(context, abbrev):
    context.looked_up = context.category_set.by_abbrev.get(abbrev)


@then('the resolved category has code "{code}"')
def step_resolved_code(context, code):
    assert context.looked_up is not None, "No category found for abbreviation"
    assert context.looked_up.code == code, (
        f"Expected code={code!r}, got {context.looked_up.code!r}"
    )
