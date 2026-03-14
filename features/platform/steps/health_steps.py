"""Step definitions for tier-0 component health scenarios."""

import os

import requests
from behave import given, then, when

from features.platform.steps.helpers import (
    PROJECT_ROOT,
    atlas_admin_api,
    atlas_api,
    impala_conn,
    impala_execute,
    kudu_master_api,
    pg_conn,
    run_cmd,
)


# ── Kerberos steps ─────────────────────────────────────────────────────────


@when('I run kinit for "{principal}" with password "{password}"')
def step_kinit(context, principal, password):
    result = run_cmd(
        ["kinit", principal],
        input=password + "\n",
        env={**os.environ, "KRB5CCNAME": os.environ.get("KRB5CCNAME", "/tmp/krb5cc_test")},
    )
    context.kinit_result = result


@then("kinit succeeds")
def step_kinit_succeeds(context):
    assert context.kinit_result.returncode == 0, (
        f"kinit failed: {context.kinit_result.stderr}"
    )


@then('klist shows a TGT for "{principal}"')
def step_klist_tgt(context, principal):
    result = run_cmd(["klist"])
    assert result.returncode == 0, f"klist failed: {result.stderr}"
    # The principal realm should appear in klist output
    realm = principal.split("@")[1] if "@" in principal else ""
    assert realm in result.stdout or principal in result.stdout, (
        f"TGT for {principal} not found in klist output:\n{result.stdout}"
    )


@then('the keytab at "{path}" exists')
def step_keytab_exists(context, path):
    full_path = os.path.join(PROJECT_ROOT, path)
    assert os.path.isfile(full_path), f"Keytab not found at {full_path}"
    context.keytab_path = full_path


@then('ktutil shows principal "{principal}" in the keytab')
def step_ktutil_principal(context, principal):
    keytab_path = getattr(context, "keytab_path", None)
    assert keytab_path, "No keytab path set — run the keytab exists step first"
    # Use klist -k to inspect keytab contents
    result = run_cmd(["klist", "-k", keytab_path])
    assert result.returncode == 0, f"klist -k failed: {result.stderr}"
    assert principal in result.stdout, (
        f"Principal {principal} not found in keytab:\n{result.stdout}"
    )


@when("I run kadmin.local to list principals")
def step_kadmin_list(context):
    kdc_dir = os.path.join(PROJECT_ROOT, ".devenv", "kdc")
    result = run_cmd(
        ["kadmin.local", "-q", "listprincs"],
        env={
            **os.environ,
            "KRB5_CONFIG": os.path.join(kdc_dir, "krb5.conf"),
            "KRB5_KDC_PROFILE": os.path.join(kdc_dir, "kdc.conf"),
        },
    )
    context.kadmin_result = result


@then('the output contains "{text}"')
def step_output_contains(context, text):
    result = getattr(context, "kadmin_result", None)
    assert result is not None, "No kadmin result — run kadmin step first"
    combined = result.stdout + result.stderr
    assert text in combined, (
        f"'{text}' not found in kadmin output:\n{combined}"
    )


# ── PostgreSQL steps ───────────────────────────────────────────────────────


@when('I connect to the "{dbname}" database')
def step_connect_db(context, dbname):
    try:
        context.pg_connection = pg_conn(dbname=dbname)
        context.pg_connected = True
    except Exception as e:
        context.pg_connected = False
        context.pg_error = str(e)


@then("the connection succeeds")
def step_connection_succeeds(context):
    assert getattr(context, "pg_connected", False), (
        f"PostgreSQL connection failed: {getattr(context, 'pg_error', 'unknown')}"
    )


@then('extension "{ext}" is loaded')
def step_extension_loaded(context, ext):
    conn = context.pg_connection
    cur = conn.execute(
        "SELECT extname FROM pg_extension WHERE extname = %s", (ext,)
    )
    row = cur.fetchone()
    assert row is not None, f"Extension '{ext}' is not installed"


@when("I list PostgreSQL databases")
def step_list_databases(context):
    conn = pg_conn(dbname="postgres")
    cur = conn.execute("SELECT datname FROM pg_database")
    context.pg_databases = [row[0] for row in cur.fetchall()]
    conn.close()


@then('database "{dbname}" exists')
def step_database_exists(context, dbname):
    assert dbname in context.pg_databases, (
        f"Database '{dbname}' not found. Available: {context.pg_databases}"
    )


@then('table "{table}" exists')
def step_table_exists(context, table):
    conn = context.pg_connection
    cur = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name = %s AND table_schema = 'public'",
        (table,),
    )
    row = cur.fetchone()
    assert row is not None, f"Table '{table}' not found in database"


# ── Atlas steps ────────────────────────────────────────────────────────────


@when("I call the Atlas version endpoint")
def step_atlas_version(context):
    try:
        context.atlas_response = atlas_admin_api("/admin/version")
    except requests.ConnectionError as e:
        assert False, f"Atlas not reachable: {e}"


@then("the response status is {code:d}")
def step_response_status(context, code):
    resp = getattr(context, "atlas_response", None)
    if resp is None:
        resp = getattr(context, "http_response", None)
    assert resp is not None, "No HTTP response available"
    assert resp.status_code == code, (
        f"Expected status {code}, got {resp.status_code}: {resp.text[:200]}"
    )


@then("the response contains a version string")
def step_response_has_version(context):
    data = context.atlas_response.json()
    version = data.get("Version") or data.get("version")
    assert version, f"No version found in Atlas response: {data}"


@when("I list Atlas type definition headers")
def step_atlas_list_types(context):
    context.atlas_response = atlas_api("/types/typedefs/headers")


@then("at least {n:d} type definitions exist")
def step_at_least_n_types(context, n):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Types headers failed (status {resp.status_code}): {resp.text[:200]}"
    )
    headers = resp.json()
    assert isinstance(headers, list), f"Expected list, got {type(headers)}"
    assert len(headers) >= n, (
        f"Expected at least {n} type definitions, got {len(headers)}"
    )


@when('I search Atlas for type "{type_name}"')
def step_atlas_type_search(context, type_name):
    context.atlas_response = atlas_api(f"/types/typedef/name/{type_name}")


@then("the type definition exists")
def step_type_def_exists(context):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Type not found (status {resp.status_code}): {resp.text[:200]}"
    )


@when('I perform an Atlas basic search for "{query}"')
def step_atlas_basic_search(context, query):
    context.atlas_response = atlas_api(
        "/search/basic", params={"query": query, "limit": 10}
    )


@then("the search returns at least {n:d} result")
def step_search_at_least_n(context, n):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Search failed (status {resp.status_code}): {resp.text[:300]}"
    )
    data = resp.json()
    entities = data.get("entities", [])
    assert len(entities) >= n, (
        f"Expected at least {n} search result(s), got {len(entities)}"
    )


@then('the search results contain entity "{qn}"')
def step_search_results_contain(context, qn):
    data = context.atlas_response.json()
    entities = data.get("entities", [])
    found = any(
        e.get("attributes", {}).get("qualifiedName") == qn for e in entities
    )
    assert found, (
        f"Entity '{qn}' not found in search results: "
        f"{[e.get('attributes', {}).get('qualifiedName') for e in entities]}"
    )


# ── Atlas type CRUD steps ─────────────────────────────────────────────────


@when('I create Atlas entity type "{name}" with attributes:')
def step_create_entity_type(context, name):
    attr_defs = []
    for row in context.table:
        attr_defs.append({
            "name": row["name"],
            "typeName": row["type"],
            "isOptional": True,
            "cardinality": "SINGLE",
            "isUnique": row["name"] == "qualifiedName",
            "isIndexable": True,
        })
    body = {
        "entityDefs": [{
            "name": name,
            "superTypes": ["Referenceable"],
            "attributeDefs": attr_defs,
        }]
    }
    context.atlas_response = atlas_api(
        "/types/typedefs", method="POST", json=body
    )


@given('Atlas entity type "{name}" exists')
def step_ensure_entity_type(context, name):
    resp = atlas_api(f"/types/entitydef/name/{name}")
    if resp.status_code == 200:
        return
    # Create a minimal type with standard attributes
    body = {
        "entityDefs": [{
            "name": name,
            "superTypes": ["Referenceable"],
            "attributeDefs": [
                {"name": "name", "typeName": "string", "isOptional": True,
                 "cardinality": "SINGLE", "isUnique": False, "isIndexable": True},
                {"name": "description", "typeName": "string", "isOptional": True,
                 "cardinality": "SINGLE", "isUnique": False, "isIndexable": True},
            ],
        }]
    }
    resp = atlas_api("/types/typedefs", method="POST", json=body)
    assert resp.status_code == 200, (
        f"Failed to create entity type '{name}' (status {resp.status_code}): {resp.text[:300]}"
    )


# ── Atlas entity CRUD steps ───────────────────────────────────────────────


def _find_entity_guid(type_name, qualified_name):
    """Look up an entity GUID by type and qualifiedName."""
    resp = atlas_api(
        f"/entity/uniqueAttribute/type/{type_name}",
        params={"attr:qualifiedName": qualified_name},
    )
    if resp.status_code == 200:
        return resp.json().get("entity", {}).get("guid")
    return None


@when('I create an Atlas entity of type "{type_name}":')
def step_create_entity(context, type_name):
    attributes = {"qualifiedName": f"test://auto/{type_name}"}
    for row in context.table:
        attributes[row["attribute"]] = row["value"]
    body = {
        "entity": {
            "typeName": type_name,
            "attributes": attributes,
        }
    }
    context.atlas_response = atlas_api("/entity", method="POST", json=body)
    context.atlas_entity_type = type_name


@then("the entity is created successfully")
def step_entity_created(context):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Entity creation failed (status {resp.status_code}): {resp.text[:300]}"
    )
    data = resp.json()
    guids = data.get("guidAssignments", {})
    mutated = data.get("mutatedEntities", {})
    created = mutated.get("CREATE", []) + mutated.get("UPDATE", [])
    assert guids or created, f"No entity created: {data}"
    # Store the guid for later use
    if created:
        context.atlas_entity_guid = created[0].get("guid")
    elif guids:
        context.atlas_entity_guid = list(guids.values())[0]


@when('I retrieve the Atlas entity by qualifiedName "{qn}"')
def step_retrieve_entity_by_qn(context, qn):
    type_name = getattr(context, "atlas_entity_type", "signals_test_asset")
    context.atlas_response = atlas_api(
        f"/entity/uniqueAttribute/type/{type_name}",
        params={"attr:qualifiedName": qn},
    )


@then('the entity attribute "{attr}" is "{value}"')
def step_entity_attribute_is(context, attr, value):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Entity retrieval failed (status {resp.status_code}): {resp.text[:300]}"
    )
    entity = resp.json().get("entity", {})
    attrs = entity.get("attributes", {})
    actual = attrs.get(attr)
    assert str(actual) == value, (
        f"Expected attribute '{attr}' = '{value}', got '{actual}'"
    )


@given('Atlas entity "{qn}" of type "{type_name}" exists')
def step_ensure_entity(context, qn, type_name):
    # Check if entity already exists
    resp = atlas_api(
        f"/entity/uniqueAttribute/type/{type_name}",
        params={"attr:qualifiedName": qn},
    )
    if resp.status_code == 200:
        context.atlas_entity_type = type_name
        return
    # Ensure the type exists first
    step_ensure_entity_type(context, type_name)
    # Create the entity
    body = {
        "entity": {
            "typeName": type_name,
            "attributes": {
                "qualifiedName": qn,
                "name": qn.rsplit("/", 1)[-1],
                "description": f"Auto-created for BDD test",
            },
        }
    }
    resp = atlas_api("/entity", method="POST", json=body)
    assert resp.status_code == 200, (
        f"Failed to create entity '{qn}' (status {resp.status_code}): {resp.text[:300]}"
    )
    context.atlas_entity_type = type_name


# ── Atlas classification steps ────────────────────────────────────────────


@when('I create Atlas classification type "{name}"')
def step_create_classification_type(context, name):
    body = {
        "classificationDefs": [{
            "name": name,
            "attributeDefs": [],
        }]
    }
    context.atlas_response = atlas_api(
        "/types/typedefs", method="POST", json=body
    )


@when('I apply classification "{cls}" to entity "{qn}"')
def step_apply_classification(context, cls, qn):
    type_name = getattr(context, "atlas_entity_type", "signals_test_asset")
    guid = _find_entity_guid(type_name, qn)
    assert guid, f"Cannot find entity '{qn}' of type '{type_name}' to classify"
    body = [{"typeName": cls}]
    context.atlas_response = atlas_api(
        f"/entity/guid/{guid}/classifications", method="POST", json=body
    )


@then('the entity "{qn}" has classification "{cls}"')
def step_entity_has_classification(context, qn, cls):
    type_name = getattr(context, "atlas_entity_type", "signals_test_asset")
    resp = atlas_api(
        f"/entity/uniqueAttribute/type/{type_name}",
        params={"attr:qualifiedName": qn},
    )
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


# ── Atlas suggestion steps ────────────────────────────────────────────────


@when('I request Atlas suggestions for prefix "{prefix}"')
def step_atlas_suggestions(context, prefix):
    context.atlas_response = atlas_api(
        "/search/suggestions", params={"prefixString": prefix}
    )


@then('the suggestions include "{text}"')
def step_suggestions_include(context, text):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Suggestions failed (status {resp.status_code}): {resp.text[:300]}"
    )
    data = resp.json()
    suggestions = data.get("suggestions", [])
    # Suggestions may contain dicts with a "name" or just strings
    names = []
    for s in suggestions:
        if isinstance(s, dict):
            names.append(s.get("name", ""))
        else:
            names.append(str(s))
    assert any(text in n for n in names), (
        f"'{text}' not found in suggestions: {names}"
    )


# ── Atlas glossary steps ──────────────────────────────────────────────────


@when('I create an Atlas glossary "{name}"')
def step_create_glossary(context, name):
    body = {"name": name, "shortDescription": f"BDD test glossary: {name}"}
    context.atlas_response = atlas_api("/glossary", method="POST", json=body)


@then("the glossary is created successfully")
def step_glossary_created(context):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Glossary creation failed (status {resp.status_code}): {resp.text[:300]}"
    )
    data = resp.json()
    guid = data.get("guid")
    assert guid, f"No guid in glossary response: {data}"
    context.atlas_glossary_guid = guid


@when('I create a term "{term}" in glossary "{glossary}" with description "{desc}"')
def step_create_glossary_term(context, term, glossary, desc):
    # Find the glossary guid
    glossary_guid = getattr(context, "atlas_glossary_guid", None)
    if not glossary_guid:
        # Look up by name
        resp = atlas_api("/glossary")
        assert resp.status_code == 200, f"Failed to list glossaries: {resp.text[:200]}"
        for g in resp.json():
            if g.get("name") == glossary:
                glossary_guid = g.get("guid")
                break
    assert glossary_guid, f"Glossary '{glossary}' not found"
    body = {
        "name": term,
        "shortDescription": desc,
        "anchor": {"glossaryGuid": glossary_guid},
    }
    context.atlas_response = atlas_api("/glossary/term", method="POST", json=body)


@then("the term is created successfully")
def step_term_created(context):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Term creation failed (status {resp.status_code}): {resp.text[:300]}"
    )
    data = resp.json()
    assert data.get("guid"), f"No guid in term response: {data}"


@when('I retrieve the glossary "{name}" with terms')
def step_retrieve_glossary_terms(context, name):
    # Find glossary guid by name
    glossary_guid = getattr(context, "atlas_glossary_guid", None)
    if not glossary_guid:
        resp = atlas_api("/glossary")
        assert resp.status_code == 200, f"Failed to list glossaries: {resp.text[:200]}"
        for g in resp.json():
            if g.get("name") == name:
                glossary_guid = g.get("guid")
                break
    assert glossary_guid, f"Glossary '{name}' not found"
    context.atlas_response = atlas_api(f"/glossary/{glossary_guid}/terms")


@then('the glossary contains term "{term}"')
def step_glossary_has_term(context, term):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Glossary term retrieval failed (status {resp.status_code}): {resp.text[:300]}"
    )
    terms = resp.json()
    term_names = [t.get("name", "") for t in terms]
    assert term in term_names, (
        f"Term '{term}' not found in glossary. Has: {term_names}"
    )


# ── Atlas lineage steps ──────────────────────────────────────────────────


@given('Atlas entity "{qn}" of type "{type_name}" exists with lineage from "{src}" to "{tgt}"')
def step_ensure_process_with_lineage(context, qn, type_name, src, tgt):
    # Ensure the process type entity exists (Process is a built-in Atlas type)
    resp = atlas_api(
        f"/entity/uniqueAttribute/type/{type_name}",
        params={"attr:qualifiedName": qn},
    )
    if resp.status_code == 200:
        return
    # Look up source and target GUIDs
    src_guid = _find_entity_guid("DataSet", src)
    tgt_guid = _find_entity_guid("DataSet", tgt)
    assert src_guid, f"Source entity '{src}' not found"
    assert tgt_guid, f"Target entity '{tgt}' not found"
    body = {
        "entity": {
            "typeName": type_name,
            "attributes": {
                "qualifiedName": qn,
                "name": qn.rsplit("/", 1)[-1],
                "description": "BDD lineage test process",
                "inputs": [{"guid": src_guid, "typeName": "DataSet"}],
                "outputs": [{"guid": tgt_guid, "typeName": "DataSet"}],
            },
        }
    }
    resp = atlas_api("/entity", method="POST", json=body)
    assert resp.status_code == 200, (
        f"Failed to create process entity '{qn}' (status {resp.status_code}): {resp.text[:300]}"
    )


@when('I query Atlas lineage for "{qn}" with direction "{direction}"')
def step_query_lineage(context, qn, direction):
    type_name = getattr(context, "atlas_entity_type", "DataSet")
    context.atlas_response = atlas_api(
        f"/lineage/uniqueAttribute/type/{type_name}",
        params={"attr:qualifiedName": qn, "direction": direction, "depth": 3},
    )


@then('the lineage includes "{qn}"')
def step_lineage_includes(context, qn):
    resp = context.atlas_response
    assert resp.status_code == 200, (
        f"Lineage query failed (status {resp.status_code}): {resp.text[:300]}"
    )
    data = resp.json()
    # Lineage response has guidEntityMap with entity details
    guid_map = data.get("guidEntityMap", {})
    found_qns = [
        e.get("attributes", {}).get("qualifiedName")
        for e in guid_map.values()
    ]
    assert qn in found_qns, (
        f"Entity '{qn}' not found in lineage. Found: {found_qns}"
    )


# ── Kudu steps ─────────────────────────────────────────────────────────────


@when("I request the Kudu master status page")
def step_kudu_master_status(context):
    try:
        context.http_response = kudu_master_api("/")
    except requests.ConnectionError as e:
        assert False, f"Kudu master not reachable: {e}"


@when("I request the Kudu master tablet servers list")
def step_kudu_tservers(context):
    try:
        # /dump-entities returns JSON with tablet_servers array
        context.http_response = kudu_master_api("/dump-entities")
    except requests.ConnectionError as e:
        assert False, f"Kudu master not reachable: {e}"


@then("at least {n:d} tablet server is registered")
def step_tserver_count(context, n):
    resp = context.http_response
    assert resp.status_code == 200, f"Kudu dump-entities error: {resp.status_code}"
    data = resp.json()
    tservers = [ts for ts in data.get("tablet_servers", []) if ts.get("live")]
    assert len(tservers) >= n, (
        f"Expected at least {n} live tablet server(s), got {len(tservers)}"
    )


@when('I create a Kudu test table "{table}" via Impala')
def step_create_kudu_test_table(context, table):
    db = table.split(".", 1)[0] if "." in table else "default"
    impala_execute(f"CREATE DATABASE IF NOT EXISTS {db}")
    impala_execute(f"DROP TABLE IF EXISTS {table}")
    impala_execute(
        f"CREATE TABLE {table} ("
        f"  id BIGINT PRIMARY KEY, val STRING"
        f") PARTITION BY HASH (id) PARTITIONS 2 STORED AS KUDU"
    )


@when('I insert a row into "{table}"')
def step_insert_row(context, table):
    impala_execute(f"INSERT INTO {table} VALUES (1, 'health-check')")


@when('I select from "{table}"')
def step_select_from(context, table):
    context.select_result = impala_execute(
        f"SELECT id, val FROM {table} WHERE id = 1", fetch=True
    )


@then("the result contains the inserted row")
def step_result_has_row(context):
    rows = context.select_result
    assert rows and len(rows) > 0, "No rows returned"
    assert rows[0][0] == 1, f"Expected id=1, got {rows[0][0]}"
    assert rows[0][1] == "health-check", f"Expected val='health-check', got {rows[0][1]}"


@then('I drop table "{table}"')
def step_drop_table(context, table):
    impala_execute(f"DROP TABLE IF EXISTS {table}")


# ── Impala steps ───────────────────────────────────────────────────────────


@when("I connect to Impala via JDBC")
def step_impala_connect(context):
    try:
        context.impala_connection = impala_conn()
        context.impala_connected = True
    except Exception as e:
        context.impala_connected = False
        assert False, f"Impala connection failed: {e}"


@when('I run "{sql}"')
def step_run_sql(context, sql):
    context.sql_result = impala_execute(sql, fetch=True)


@then("the query result is {n:d}")
def step_query_result_is(context, n):
    result = context.sql_result
    assert result and result[0][0] == n, (
        f"Expected {n}, got {result[0][0] if result else 'no result'}"
    )


@when("I request the Impala catalogd web UI")
def step_impala_catalogd_ui(context):
    try:
        context.http_response = requests.get(
            "http://localhost:25020/", timeout=10
        )
    except requests.ConnectionError as e:
        assert False, f"Impala catalogd not reachable: {e}"


@then('the result contains "{text}"')
def step_result_contains(context, text):
    result = context.sql_result
    assert result is not None, "No SQL result available"
    # Flatten results for searching
    found = any(
        text.lower() in str(cell).lower()
        for row in result
        for cell in row
    )
    assert found, f"'{text}' not found in query results"
