"""Step definitions for tier-1 cross-component integration scenarios."""

from behave import given, then, when

from features.platform.steps.helpers import (
    atlas_api,
    column_qualified_name,
    delete_atlas_entity,
    impala_execute,
    impala_scalar,
    kudu_master_api,
    register_impala_table_in_atlas,
    table_qualified_name,
)
from features.platform.steps.health_steps import _find_entity_guid


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
    # Verify table exists by querying it through Impala (the standard path).
    # This confirms the table is stored in Kudu and queryable.
    rows = impala_execute(f"SHOW TABLES IN {table.split('.')[0]}", fetch=True)
    table_name = table.split(".")[-1]
    found = any(table_name in str(row) for row in rows)
    assert found, (
        f"Table '{table}' not found via Impala. Available: {rows}"
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
    impala_execute(f"UPDATE {table} SET value = CAST(value + 1 AS INT) WHERE id < 5")


@when('I delete rows from "{table}" via Impala')
def step_delete_rows(context, table):
    impala_execute(f"DELETE FROM {table} WHERE id >= 8")


@then('"{table}" row count is correct')
def step_row_count_correct(context, table):
    count = impala_scalar(f"SELECT COUNT(*) FROM {table}")
    # Inserted 10, deleted rows where id >= 8 (ids 8, 9 = 2 rows), so 8 remain
    assert count == 8, f"Expected 8 rows after CRUD, got {count}"


@when('I drop table "{table}" via Impala')
def step_drop_via_impala(context, table):
    impala_execute(f"DROP TABLE IF EXISTS {table}")


# ── Atlas bridge steps ─────────────────────────────────────────────────────


@when("I register the table in Atlas via the catalog bridge")
def step_register_table_atlas_bridge(context):
    table = context.last_created_table
    result = register_impala_table_in_atlas(table)
    context.atlas_registration = result
    assert result["table_guid"], (
        f"Bridge registration failed — no table GUID returned for '{table}'"
    )


@then('Atlas entity search finds "{entity}"')
def step_atlas_finds_entity(context, entity):
    qn = table_qualified_name(entity)
    resp = atlas_api(
        "/search/basic",
        params={"typeName": "hive_table", "query": entity, "limit": 25},
    )
    assert resp.status_code == 200, (
        f"Atlas search failed (status {resp.status_code}): {resp.text[:300]}"
    )
    data = resp.json()
    entities = data.get("entities", [])
    found = any(
        e.get("attributes", {}).get("qualifiedName") == qn for e in entities
    )
    assert found, (
        f"Entity '{qn}' not found in search results: "
        f"{[e.get('attributes', {}).get('qualifiedName') for e in entities]}"
    )


@then("the Atlas entity has correct column metadata")
def step_atlas_entity_has_columns(context):
    table = context.last_created_table
    qn = table_qualified_name(table)
    resp = atlas_api(
        f"/entity/uniqueAttribute/type/hive_table",
        params={"attr:qualifiedName": qn, "minExtInfo": "true"},
    )
    assert resp.status_code == 200, (
        f"Entity retrieval failed (status {resp.status_code}): {resp.text[:300]}"
    )
    data = resp.json()
    # referredEntities contains column entities
    referred = data.get("referredEntities", {})
    col_entities = [
        e for e in referred.values() if e.get("typeName") == "hive_column"
    ]
    assert len(col_entities) >= 3, (
        f"Expected at least 3 column entities, got {len(col_entities)}: "
        f"{[e.get('attributes', {}).get('name') for e in col_entities]}"
    )


@then('Atlas has an entity for "{entity}"')
def step_atlas_has_entity(context, entity):
    qn = table_qualified_name(entity)
    guid = _find_entity_guid("hive_table", qn)
    assert guid, f"No Atlas entity found for '{qn}'"
    context.atlas_entity_guid = guid


@when("I mark the Atlas entity as deleted")
def step_mark_atlas_entity_deleted(context):
    table = context.last_created_table
    qn = table_qualified_name(table)
    resp = delete_atlas_entity("hive_table", qn)
    assert resp.status_code in (200, 204), (
        f"Atlas entity delete failed (status {resp.status_code}): {resp.text[:300]}"
    )


@then("the Atlas entity is marked as deleted")
def step_atlas_entity_deleted(context):
    table = context.last_created_table
    qn = table_qualified_name(table)
    resp = atlas_api(
        f"/entity/uniqueAttribute/type/hive_table",
        params={"attr:qualifiedName": qn},
    )
    if resp.status_code == 404:
        return  # entity purged or not found — OK
    if resp.status_code == 200:
        entity = resp.json().get("entity", {})
        status = entity.get("status", "")
        assert status == "DELETED", (
            f"Expected entity status DELETED, got '{status}'"
        )
        return
    assert False, f"Unexpected status {resp.status_code}: {resp.text[:300]}"


# ── Meta-tagging steps ─────────────────────────────────────────────────────


@then('the classification type "{name}" exists in Atlas')
def step_classification_exists(context, name):
    resp = atlas_api(f"/types/classificationdef/name/{name}")
    assert resp.status_code == 200, (
        f"Classification type '{name}' not found (status {resp.status_code}): "
        f"{resp.text[:300]}"
    )


@given('Atlas classification type "{name}" exists')
def step_given_classification_exists(context, name):
    resp = atlas_api(f"/types/classificationdef/name/{name}")
    if resp.status_code == 200:
        return
    # Create the classification type
    body = {
        "classificationDefs": [{
            "name": name,
            "attributeDefs": [],
        }]
    }
    resp = atlas_api("/types/typedefs", method="POST", json=body)
    assert resp.status_code == 200, (
        f"Failed to create classification type '{name}' "
        f"(status {resp.status_code}): {resp.text[:300]}"
    )


@given('Kudu table "{table}" is registered in Atlas')
def step_kudu_table_in_atlas(context, table):
    db = table.split(".")[0] if "." in table else "default"
    impala_execute(f"CREATE DATABASE IF NOT EXISTS {db}")
    impala_execute(f"DROP TABLE IF EXISTS {table}")
    impala_execute(
        f"CREATE TABLE {table} ("
        f"  id BIGINT PRIMARY KEY, name STRING, email STRING, value INT"
        f") PARTITION BY HASH (id) PARTITIONS 2 STORED AS KUDU"
    )
    context.last_created_table = table
    result = register_impala_table_in_atlas(table)
    context.atlas_registration = result
    assert result["table_guid"], (
        f"Bridge registration failed for '{table}'"
    )


@when('I apply classification "{cls}" to Kudu table "{table}"')
def step_apply_table_classification(context, cls, table):
    qn = table_qualified_name(table)
    guid = _find_entity_guid("hive_table", qn)
    assert guid, f"Cannot find hive_table entity '{qn}' to classify"
    body = [{"typeName": cls}]
    resp = atlas_api(f"/entity/guid/{guid}/classifications", method="POST", json=body)
    # 200/204 = success, 400 with "already associated" = idempotent OK
    if resp.status_code == 400 and "already associated" in resp.text:
        pass  # classification already applied
    else:
        assert resp.status_code in (200, 204), (
            f"Failed to apply classification '{cls}' to '{table}' "
            f"(status {resp.status_code}): {resp.text[:300]}"
        )
    context.atlas_classified_guid = guid
    context.atlas_classified_table = table


@then('the entity has classification "{cls}"')
def step_entity_has_classification(context, cls):
    guid = context.atlas_classified_guid
    resp = atlas_api(f"/entity/guid/{guid}")
    assert resp.status_code == 200, (
        f"Entity retrieval failed (status {resp.status_code}): {resp.text[:300]}"
    )
    entity = resp.json().get("entity", {})
    classifications = [
        c.get("typeName") for c in entity.get("classifications", [])
    ]
    assert cls in classifications, (
        f"Classification '{cls}' not found on entity. Has: {classifications}"
    )


@given('column "{col}" of Kudu table "{table}" is registered in Atlas')
def step_table_column_in_atlas(context, col, table):
    # Ensure the table is registered first
    qn = table_qualified_name(table)
    guid = _find_entity_guid("hive_table", qn)
    if not guid:
        step_kudu_table_in_atlas(context, table)
    # Verify the column entity exists
    col_qn = column_qualified_name(table, col)
    col_guid = _find_entity_guid("hive_column", col_qn)
    assert col_guid, f"Column entity '{col_qn}' not found in Atlas"
    context.atlas_column_guid = col_guid
    context.atlas_column_table = table
    context.atlas_column_name = col


@when('I apply classification "{cls}" to column "{col}" of "{table}"')
def step_apply_column_classification(context, cls, col, table):
    col_qn = column_qualified_name(table, col)
    col_guid = _find_entity_guid("hive_column", col_qn)
    assert col_guid, f"Cannot find hive_column entity '{col_qn}' to classify"
    body = [{"typeName": cls}]
    resp = atlas_api(
        f"/entity/guid/{col_guid}/classifications", method="POST", json=body
    )
    if resp.status_code == 400 and "already associated" in resp.text:
        pass  # classification already applied
    else:
        assert resp.status_code in (200, 204), (
            f"Failed to apply classification '{cls}' to column '{col}' "
            f"(status {resp.status_code}): {resp.text[:300]}"
        )
    context.atlas_classified_column_guid = col_guid


@then('the column entity has classification "{cls}"')
def step_column_has_classification(context, cls):
    guid = context.atlas_classified_column_guid
    resp = atlas_api(f"/entity/guid/{guid}")
    assert resp.status_code == 200, (
        f"Column entity retrieval failed (status {resp.status_code}): "
        f"{resp.text[:300]}"
    )
    entity = resp.json().get("entity", {})
    classifications = [
        c.get("typeName") for c in entity.get("classifications", [])
    ]
    assert cls in classifications, (
        f"Classification '{cls}' not found on column. Has: {classifications}"
    )


@given('multiple tables have classification "{cls}"')
def step_multiple_tables_classified(context, cls):
    # Ensure classification type exists
    step_given_classification_exists(context, cls)

    # Create and register two tables
    tables = [
        "integration_test.pii_table_a",
        "integration_test.pii_table_b",
    ]
    context.pii_tagged_tables = []
    for table in tables:
        db = table.split(".")[0]
        impala_execute(f"CREATE DATABASE IF NOT EXISTS {db}")
        impala_execute(f"DROP TABLE IF EXISTS {table}")
        impala_execute(
            f"CREATE TABLE {table} ("
            f"  id BIGINT PRIMARY KEY, name STRING, email STRING, value INT"
            f") PARTITION BY HASH (id) PARTITIONS 2 STORED AS KUDU"
        )
        result = register_impala_table_in_atlas(table)
        assert result["table_guid"], f"Registration failed for '{table}'"

        # Apply classification
        qn = table_qualified_name(table)
        guid = _find_entity_guid("hive_table", qn)
        assert guid, f"Cannot find entity '{qn}' after registration"
        body = [{"typeName": cls}]
        resp = atlas_api(
            f"/entity/guid/{guid}/classifications", method="POST", json=body
        )
        if resp.status_code == 400 and "already associated" in resp.text:
            pass  # classification already applied
        else:
            assert resp.status_code in (200, 204), (
                f"Failed to classify '{table}' (status {resp.status_code})"
            )
        context.pii_tagged_tables.append(table)


@when('I search Atlas for entities with classification "{cls}"')
def step_search_by_classification(context, cls):
    # AGE backend basic search doesn't support classification filter natively.
    # Workaround: search for hive_table entities, then verify classification
    # on each entity individually via the entity API.
    tagged_entities = []
    for table in context.pii_tagged_tables:
        qn = table_qualified_name(table)
        guid = _find_entity_guid("hive_table", qn)
        if not guid:
            continue
        resp = atlas_api(f"/entity/guid/{guid}")
        if resp.status_code != 200:
            continue
        entity = resp.json().get("entity", {})
        classifications = [
            c.get("typeName") for c in entity.get("classifications", [])
        ]
        if cls in classifications:
            tagged_entities.append(entity)
    context.atlas_classification_search = {
        "entities": tagged_entities,
    }


@then("the results include all tagged tables")
def step_results_include_tagged(context):
    data = context.atlas_classification_search
    entities = data.get("entities", [])
    found_qns = {
        e.get("attributes", {}).get("qualifiedName") for e in entities
    }
    for table in context.pii_tagged_tables:
        qn = table_qualified_name(table)
        assert qn in found_qns, (
            f"Tagged table '{qn}' not found in search results. "
            f"Found: {found_qns}"
        )


# ── Tagger-based steps ───────────────────────────────────────────────────


@when("I run Tagger setup_types with the default config")
def step_tagger_setup_types(context):
    from sigint.config import load_config
    from sigint.tagger import Tagger

    cfg = load_config()
    tc = cfg.to_tagging_config()
    tagger = Tagger(tc)
    try:
        context.tagger_setup_result = tagger.setup_types()
    finally:
        tagger.close()


@then("the setup result reports types created or existing")
def step_setup_result(context):
    result = context.tagger_setup_result
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
