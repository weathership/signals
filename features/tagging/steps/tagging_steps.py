"""Step definitions for pipeline_tagging.feature (tier-1)."""

from behave import given, then, when

from features.platform.steps.helpers import (
    impala_execute,
    register_impala_table_in_atlas,
)


@given('Kudu table "{table}" with typed columns:')
def step_create_typed_table(context, table):
    db = table.split(".")[0] if "." in table else "default"
    impala_execute(f"CREATE DATABASE IF NOT EXISTS {db}")
    impala_execute(f"DROP TABLE IF EXISTS {table}")

    columns = []
    key_col = None
    for row in context.table:
        col = row["column"]
        typ = row["type"]
        columns.append(f"{col} {typ}")
        if key_col is None and typ == "BIGINT":
            key_col = col

    col_defs = ", ".join(columns)
    key_col = key_col or columns[0].split()[0]
    impala_execute(
        f"CREATE TABLE {table} ({col_defs}, "
        f"PRIMARY KEY ({key_col})) "
        f"PARTITION BY HASH ({key_col}) PARTITIONS 2 STORED AS KUDU"
    )
    context.last_created_table = table
    context.tagging_table = table
    context.tagging_columns = [row["column"] for row in context.table]


@given("the table has representative data inserted")
def step_insert_representative(context):
    table = context.tagging_table
    cols = context.tagging_columns

    # Build representative rows based on column types
    rows = []
    sample_data = {
        "email": ["'alice@example.com'", "'bob@test.org'", "'carol@domain.co.uk'"],
        "phone_number": ["'555-0100'", "'555-0200'", "'555-0300'"],
        "ssn": ["'123-45-6789'", "'987-65-4321'", "'111-22-3333'"],
        "full_name": ["'Alice Smith'", "'Bob Jones'", "'Carol White'"],
    }

    for i in range(3):
        vals = []
        for col in cols:
            if col == "id":
                vals.append(str(i))
            elif col in sample_data:
                vals.append(sample_data[col][i])
            else:
                vals.append(f"'value_{i}'")
        rows.append(f"({', '.join(vals)})")

    impala_execute(f"INSERT INTO {table} VALUES {', '.join(rows)}")


@given("the table is registered in Atlas")
def step_register_in_atlas(context):
    result = register_impala_table_in_atlas(context.tagging_table)
    context.atlas_registration = result
    assert result["table_guid"], (
        f"Atlas registration failed for '{context.tagging_table}'"
    )


@when('I run the Tagger on "{table}"')
def step_run_tagger(context, table):
    from sigint.config import load_config
    from sigint.tagger import Tagger

    cfg = load_config(overrides={"tables": [table], "dry_run": False})
    tc = cfg.to_tagging_config()
    tagger = Tagger(tc)
    try:
        context.tag_report = tagger.run()
    finally:
        tagger.close()


@when('I run the Tagger in dry-run mode on "{table}"')
def step_run_tagger_dry(context, table):
    from sigint.config import load_config
    from sigint.tagger import Tagger

    cfg = load_config(overrides={"tables": [table], "dry_run": True})
    tc = cfg.to_tagging_config()
    tagger = Tagger(tc)
    try:
        context.tag_report = tagger.run()
    finally:
        tagger.close()


@then("the TagReport shows tables_processed = {n:d}")
def step_tables_processed(context, n):
    assert context.tag_report.tables_processed == n, (
        f"Expected tables_processed={n}, "
        f"got {context.tag_report.tables_processed}"
    )


@then("the TagReport shows columns_classified >= {n:d}")
def step_columns_classified(context, n):
    assert context.tag_report.columns_classified >= n, (
        f"Expected columns_classified >= {n}, "
        f"got {context.tag_report.columns_classified}"
    )


@then("the TagReport shows columns_tagged = {n:d}")
def step_columns_tagged(context, n):
    assert context.tag_report.columns_tagged == n, (
        f"Expected columns_tagged={n}, "
        f"got {context.tag_report.columns_tagged}"
    )


@then("the TagReport shows columns_tagged >= {n:d}")
def step_columns_tagged_ge(context, n):
    assert context.tag_report.columns_tagged >= n, (
        f"Expected columns_tagged >= {n}, "
        f"got {context.tag_report.columns_tagged}"
    )
