"""Step definitions for tier-1 cross-component integration scenarios."""

from behave import given, then, when

from features.platform.steps.helpers import (
    impala_execute,
    impala_scalar,
    kudu_master_api,
)


# ── Catalog sync steps ─────────────────────────────────────────────────────


@given('database "{db}" exists in Impala')
def step_db_exists_impala(context, db):
    impala_execute(f"CREATE DATABASE IF NOT EXISTS {db}")


@when('I create Kudu table "{table}" via Impala')
def step_create_kudu_table(context, table):
    db = table.split(".")[0] if "." in table else "default"
    impala_execute(f"CREATE DATABASE IF NOT EXISTS {db}")
    impala_execute(f"DROP TABLE IF EXISTS {table}")
    impala_execute(
        f"CREATE TABLE {table} ("
        f"  id BIGINT PRIMARY KEY, name STRING, value INT"
        f") PARTITION BY HASH (id) PARTITIONS 2 STORED AS KUDU"
    )
    context.last_created_table = table


@then("the table exists in Kudu master's table list")
def step_table_in_kudu(context):
    table = context.last_created_table
    # Kudu stores tables with the Impala database prefix
    resp = kudu_master_api("/api/v1/tables")
    assert resp.status_code == 200, f"Kudu API error: {resp.text[:200]}"
    tables_data = resp.json()
    # Kudu /api/v1/tables returns a list of table objects
    if isinstance(tables_data, list):
        table_names = [t.get("table_name", t.get("name", "")) for t in tables_data]
    else:
        table_names = [
            t.get("table_name", t.get("name", ""))
            for t in tables_data.get("tables", [])
        ]
    # Kudu table names include "impala::" prefix for Impala-managed tables
    found = any(table in name or table.replace(".", ".") in name for name in table_names)
    assert found, (
        f"Table '{table}' not found in Kudu. Available: {table_names}"
    )


@given('Kudu table "{table}" exists')
def step_kudu_table_exists(context, table):
    db = table.split(".")[0] if "." in table else "default"
    impala_execute(f"CREATE DATABASE IF NOT EXISTS {db}")
    impala_execute(f"DROP TABLE IF EXISTS {table}")
    impala_execute(
        f"CREATE TABLE {table} ("
        f"  id BIGINT PRIMARY KEY, name STRING, value INT"
        f") PARTITION BY HASH (id) PARTITIONS 2 STORED AS KUDU"
    )
    context.last_created_table = table


@when('I insert 10 rows into "{table}" via Impala')
def step_insert_10_rows(context, table):
    values = ", ".join(f"({i}, 'row-{i}', {i * 10})" for i in range(10))
    impala_execute(f"INSERT INTO {table} VALUES {values}")


@when('I update rows in "{table}" via Impala')
def step_update_rows(context, table):
    impala_execute(f"UPDATE {table} SET value = value + 1 WHERE id < 5")


@when('I delete rows from "{table}" via Impala')
def step_delete_rows(context, table):
    impala_execute(f"DELETE FROM {table} WHERE id >= 8")


@then('"{table}" row count is correct')
def step_row_count_correct(context, table):
    count = impala_scalar(f"SELECT COUNT(*) FROM {table}")
    # Inserted 10, deleted rows where id >= 8 (ids 8, 9 = 2 rows), so 8 remain
    assert count == 8, f"Expected 8 rows after CRUD, got {count}"


# ── Atlas discovery steps (TDD) ───────────────────────────────────────────


@when("I trigger an Atlas metadata import")
def step_trigger_atlas_import(context):
    assert False, (
        "TDD: Atlas metadata import from Impala/Kudu not yet implemented. "
        "Requires Atlas hook or import API integration."
    )


@then('Atlas entity search finds "{entity}"')
def step_atlas_finds_entity(context, entity):
    assert False, (
        f"TDD: Atlas entity search for '{entity}' not yet implemented. "
        "Requires Atlas-Impala catalog bridge."
    )


@when("I wait for Atlas to process the event")
def step_wait_atlas_event(context):
    assert False, (
        "TDD: Atlas DDL event processing not yet implemented. "
        "Requires Impala Atlas hook integration."
    )


@then('Atlas has an entity for "{entity}"')
def step_atlas_has_entity(context, entity):
    assert False, (
        f"TDD: Atlas entity lookup for '{entity}' not yet implemented. "
        "Requires Atlas-Impala catalog bridge."
    )


@when('I drop table "{table}" via Impala')
def step_drop_via_impala(context, table):
    impala_execute(f"DROP TABLE IF EXISTS {table}")


@then("the Atlas entity is marked as deleted")
def step_atlas_entity_deleted(context):
    assert False, (
        "TDD: Atlas soft-delete verification not yet implemented. "
        "Requires Atlas-Impala DDL event integration."
    )


# ── Meta-tagging steps (TDD) ──────────────────────────────────────────────


@then('the classification type "{name}" exists in Atlas')
def step_classification_exists(context, name):
    assert False, (
        f"TDD: Atlas classification type verification for '{name}' not yet implemented."
    )


@given('Atlas classification type "{name}" exists')
def step_given_classification_exists(context, name):
    assert False, (
        f"TDD: Atlas classification type '{name}' prerequisite not yet implemented."
    )


@given('Kudu table "{table}" is registered in Atlas')
def step_kudu_table_in_atlas(context, table):
    assert False, (
        f"TDD: Kudu table '{table}' Atlas entity prerequisite not yet implemented. "
        "Requires Atlas-Impala catalog bridge."
    )


@then('the entity has classification "{cls}"')
def step_entity_has_classification(context, cls):
    assert False, (
        f"TDD: Entity classification verification for '{cls}' not yet implemented."
    )


@given('column "{col}" of Kudu table "{table}" is registered in Atlas')
def step_table_column_in_atlas(context, col, table):
    assert False, (
        f"TDD: Column-level Atlas entity for '{table}.{col}' not yet implemented."
    )


@when('I apply classification "{cls}" to column "{col}" of "{table}"')
def step_apply_column_classification(context, cls, col, table):
    assert False, (
        f"TDD: Column classification '{cls}' on '{table}.{col}' not yet implemented."
    )


@then('the column entity has classification "{cls}"')
def step_column_has_classification(context, cls):
    assert False, (
        f"TDD: Column classification verification for '{cls}' not yet implemented."
    )


@given('multiple tables have classification "{cls}"')
def step_multiple_tables_classified(context, cls):
    assert False, (
        f"TDD: Multiple table classification setup for '{cls}' not yet implemented."
    )


@when('I search Atlas for entities with classification "{cls}"')
def step_search_by_classification(context, cls):
    assert False, (
        f"TDD: Atlas classification search for '{cls}' not yet implemented."
    )


@then("the results include all tagged tables")
def step_results_include_tagged(context):
    assert False, (
        "TDD: Atlas classification search result verification not yet implemented."
    )
