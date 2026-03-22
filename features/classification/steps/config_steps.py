"""Step definitions for config_lifecycle.feature."""

import tempfile
from pathlib import Path

from behave import given, then, when

from features.classification.steps.helpers import register_temp_file


@when("I load the pipeline config with no overrides")
def step_load_default_config(context):
    from sigint.config import load_config

    context.cfg = load_config()


@when("I load the pipeline config with overrides")
def step_load_config_with_overrides(context):
    from sigint.config import load_config

    overrides = {}
    for row in context.table:
        key = row["field"]
        val = row["value"]
        # Coerce numeric/bool
        try:
            val = float(val)
            if val == int(val):
                val = int(val)
        except ValueError:
            if val.lower() in ("true", "false"):
                val = val.lower() == "true"
        overrides[key] = val
    context.cfg = load_config(overrides=overrides)


@then('the config has classifier_type = "{value}"')
def step_config_classifier_type(context, value):
    assert context.cfg.classifier_type == value, (
        f"Expected classifier_type={value!r}, got {context.cfg.classifier_type!r}"
    )


@then("the config has confidence_threshold = {value:g}")
def step_config_threshold(context, value):
    assert abs(context.cfg.confidence_threshold - value) < 1e-9, (
        f"Expected confidence_threshold={value}, got {context.cfg.confidence_threshold}"
    )


@then('the config has taxonomy_name = "{value}"')
def step_config_taxonomy(context, value):
    assert context.cfg.taxonomy_name == value, (
        f"Expected taxonomy_name={value!r}, got {context.cfg.taxonomy_name!r}"
    )


@then("the config has hierarchical = true")
def step_config_hierarchical_true(context):
    assert context.cfg.hierarchical is True


@given("a loaded pipeline config")
def step_loaded_config(context):
    from sigint.config import load_config

    context.cfg = load_config()


@when("I materialize the config to a temporary path")
def step_materialize_config(context):
    from sigint.config import materialize_config

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", prefix="bdd_config_", delete=False,
    )
    tmp.close()
    register_temp_file(context, tmp.name)
    materialize_config(context.cfg, tmp.name)
    context.materialized_path = tmp.name


@then('the materialized file contains "{expected}"')
def step_materialized_contains(context, expected):
    content = Path(context.materialized_path).read_text()
    assert expected in content, (
        f"Expected '{expected}' in materialized config, but not found.\n"
        f"Content:\n{content[:500]}"
    )


@given('a materialized config with classifier_type = "llm" and no API key')
def step_materialized_llm_no_key(context):
    from sigint.config import load_config, materialize_config

    cfg = load_config(overrides={"classifier_type": "llm"})
    # Force anthropic_api_key to None
    object.__setattr__(cfg, "anthropic_api_key", None)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", prefix="bdd_config_", delete=False,
    )
    tmp.close()
    register_temp_file(context, tmp.name)
    materialize_config(cfg, tmp.name)
    context.materialized_path = tmp.name


@when("I validate the materialized config")
def step_validate_config(context):
    from sigint.config import validate_materialized_config

    context.validation_errors = validate_materialized_config(
        context.materialized_path
    )


@then('the validation returns an error mentioning "{key}"')
def step_validation_error_mentions(context, key):
    assert context.validation_errors, "Expected validation errors but got none"
    all_errors = "\n".join(context.validation_errors)
    assert key in all_errors, (
        f"Expected error mentioning '{key}', got:\n{all_errors}"
    )


@given("a fully populated materialized config file")
def step_fully_populated_config(context):
    from sigint.config import load_config, materialize_config

    cfg = load_config()
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", prefix="bdd_config_", delete=False,
    )
    tmp.close()
    register_temp_file(context, tmp.name)
    materialize_config(cfg, tmp.name)
    context.materialized_path = tmp.name


@then("the validation returns no errors")
def step_validation_no_errors(context):
    assert not context.validation_errors, (
        f"Expected no errors, got: {context.validation_errors}"
    )
