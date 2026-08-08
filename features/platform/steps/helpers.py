"""Shared helpers for BDD step implementations.

Connection parameters are loaded from config/base.conf via load_config()
so the BDD framework and the application share a single source of truth.
"""

import os
import subprocess
import sys

# Disable thrift C accelerator before importing impyla.
# The C extension has PY_SSIZE_T_CLEAN issues on Python 3.12+.
sys.modules.setdefault("thrift.protocol.fastbinary", None)
sys.modules.setdefault("thrift.protocol.fastproto", None)

import psycopg
import requests
from impala.dbapi import connect as impala_connect

from sigint.config import load_config

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Load resolved config once — HOCON base.conf + env var overrides.
_CFG = load_config()

CLUSTER_NAME = _CFG.cluster_name

# Atlas RDBMS model (addons/models/2000-RDBMS) — Aegir-aligned.
# Physical Kudu names stay separate (FDW kudu_table / impala::db.table).
ATLAS_INSTANCE_TYPE = "rdbms_instance"
ATLAS_DB_TYPE = "rdbms_db"
ATLAS_TABLE_TYPE = "rdbms_table"
ATLAS_COLUMN_TYPE = "rdbms_column"
# Required attribute on rdbms_instance (Aegir uses similar free-text values).
ATLAS_RDBMS_TYPE = "Kudu"


def table_qualified_name(table_fqn):
    """Return Atlas qualifiedName for a table: 'db.table@cluster'."""
    return f"{table_fqn}@{CLUSTER_NAME}"


def column_qualified_name(table_fqn, col):
    """Return Atlas qualifiedName for a column: 'db.table.col@cluster'."""
    return f"{table_fqn}.{col}@{CLUSTER_NAME}"


def db_qualified_name(db):
    """Return Atlas qualifiedName for a database: 'db@cluster'."""
    return f"{db}@{CLUSTER_NAME}"


def instance_qualified_name(cluster=None):
    """Return Atlas qualifiedName for the lab rdbms_instance."""
    return f"instance@{(cluster or CLUSTER_NAME)}"


def pg_conn(dbname="signals"):
    """Connect to a local PostgreSQL database."""
    return psycopg.connect(host="127.0.0.1", port=5455, dbname=dbname, autocommit=True)


def impala_conn():
    """Connect to Impala via HiveServer2 (no auth)."""
    return impala_connect(
        host=_CFG.impala_host, port=_CFG.impala_port, auth_mechanism="NOSASL",
    )


def impala_execute(sql, fetch=False):
    """Execute a SQL statement on Impala and optionally fetch results."""
    conn = impala_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if fetch:
            return cur.fetchall()
        return None
    finally:
        conn.close()


def impala_scalar(sql):
    """Execute a SQL statement on Impala and return a single scalar value."""
    rows = impala_execute(sql, fetch=True)
    return rows[0][0] if rows else None


def atlas_api(path, method="GET", **kwargs):
    """Call the Atlas v2 REST API."""
    url = f"{_CFG.atlas_url}/api/atlas/v2{path}"
    auth = (_CFG.atlas_user, _CFG.atlas_password)
    return requests.request(method, url, auth=auth, timeout=60, **kwargs)


def atlas_admin_api(path, method="GET", **kwargs):
    """Call the Atlas admin REST API."""
    url = f"{_CFG.atlas_url}/api/atlas{path}"
    auth = (_CFG.atlas_user, _CFG.atlas_password)
    return requests.request(method, url, auth=auth, timeout=60, **kwargs)


def atlas_api_json(path, method="GET", **kwargs):
    """Call Atlas v2 API and return parsed JSON (raises on non-2xx)."""
    resp = atlas_api(path, method=method, **kwargs)
    resp.raise_for_status()
    return resp.json()


def kudu_master_api(path):
    """Call the Kudu master HTTP API."""
    return requests.get(f"http://127.0.0.1:8051{path}", timeout=10)


def run_cmd(cmd, **kwargs):
    """Run a shell command with standard timeout and capture."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kwargs)


def register_impala_table_in_atlas(table_fqn):
    """Register an Impala-managed Kudu table in Atlas via REST API.

    Runs DESCRIBE on the table to get columns, then creates rdbms_instance,
    rdbms_db, rdbms_table, and rdbms_column entities (Atlas 2000-RDBMS model,
    Aegir-aligned) via POST /v2/entity/bulk.

    Returns dict with table_guid, db_guid, instance_guid, and column_guids.
    """
    parts = table_fqn.split(".", 1)
    db_name = parts[0] if len(parts) == 2 else "default"
    table_name = parts[1] if len(parts) == 2 else parts[0]

    # Get column metadata from Impala
    rows = impala_execute(f"DESCRIBE {table_fqn}", fetch=True)
    assert rows, f"DESCRIBE {table_fqn} returned no results"
    columns = [(row[0], row[1], row[2] if len(row) > 2 else "") for row in rows]

    inst_qn = instance_qualified_name()
    db_qn = db_qualified_name(db_name)
    tbl_qn = table_qualified_name(table_fqn)

    # Build column entities with negative temp GUIDs (rdbms_column uses data_type)
    col_entities = []
    col_guid_map = {}
    for i, (col_name, col_type, col_comment) in enumerate(columns):
        temp_guid = f"-{10 + i}"
        col_qn = column_qualified_name(table_fqn, col_name)
        col_guid_map[col_name] = temp_guid
        col_entities.append({
            "typeName": ATLAS_COLUMN_TYPE,
            "guid": temp_guid,
            "attributes": {
                "qualifiedName": col_qn,
                "name": col_name,
                "data_type": col_type,
                "comment": col_comment or None,
                "owner": "admin",
                "table": {"guid": "-1", "typeName": ATLAS_TABLE_TYPE},
            },
        })

    # Temp GUIDs: -1 table, -100 db, -200 instance
    body = {
        "referredEntities": {
            "-200": {
                "typeName": ATLAS_INSTANCE_TYPE,
                "guid": "-200",
                "attributes": {
                    "qualifiedName": inst_qn,
                    "name": CLUSTER_NAME,
                    "rdbms_type": ATLAS_RDBMS_TYPE,
                    "platform": "signals",
                    "owner": "admin",
                },
            },
            "-100": {
                "typeName": ATLAS_DB_TYPE,
                "guid": "-100",
                "attributes": {
                    "qualifiedName": db_qn,
                    "name": db_name,
                    "owner": "admin",
                    "instance": {
                        "guid": "-200",
                        "typeName": ATLAS_INSTANCE_TYPE,
                    },
                },
            },
        },
        "entities": [{
            "typeName": ATLAS_TABLE_TYPE,
            "guid": "-1",
            "attributes": {
                "qualifiedName": tbl_qn,
                "name": table_name,
                "owner": "admin",
                "type": "TABLE",
                "db": {"guid": "-100", "typeName": ATLAS_DB_TYPE},
                "columns": [
                    {"guid": ce["guid"], "typeName": ATLAS_COLUMN_TYPE}
                    for ce in col_entities
                ],
            },
        }],
    }
    for ce in col_entities:
        body["referredEntities"][ce["guid"]] = ce

    resp = atlas_api("/entity/bulk", method="POST", json=body)
    resp.raise_for_status()
    data = resp.json()

    guid_assignments = data.get("guidAssignments", {})
    result = {
        "table_guid": guid_assignments.get("-1"),
        "db_guid": guid_assignments.get("-100"),
        "instance_guid": guid_assignments.get("-200"),
        "column_guids": {},
    }

    if not result["table_guid"]:
        mutated = data.get("mutatedEntities", {})
        for action_entities in mutated.values():
            for ent in action_entities:
                t = ent.get("typeName")
                if t == ATLAS_TABLE_TYPE:
                    result["table_guid"] = ent.get("guid")
                elif t == ATLAS_DB_TYPE:
                    result["db_guid"] = ent.get("guid")
                elif t == ATLAS_INSTANCE_TYPE:
                    result["instance_guid"] = ent.get("guid")

    for col_name, temp_guid in col_guid_map.items():
        real_guid = guid_assignments.get(temp_guid)
        if real_guid:
            result["column_guids"][col_name] = real_guid
        else:
            mutated = data.get("mutatedEntities", {})
            col_qn = column_qualified_name(table_fqn, col_name)
            for action_entities in mutated.values():
                for ent in action_entities:
                    if (ent.get("typeName") == ATLAS_COLUMN_TYPE
                            and ent.get("attributes", {}).get("qualifiedName") == col_qn):
                        result["column_guids"][col_name] = ent.get("guid")

    return result


def delete_atlas_entity(type_name, qualified_name):
    """Delete an Atlas entity by type and qualifiedName (soft-delete)."""
    resp = atlas_api(
        f"/entity/uniqueAttribute/type/{type_name}",
        method="DELETE",
        params={"attr:qualifiedName": qualified_name},
    )
    return resp


def delete_atlas_entities_by_guids(guids):
    """Delete multiple Atlas entities by GUID (soft-delete)."""
    if not guids:
        return None
    params = [("guid", g) for g in guids if g]
    if not params:
        return None
    resp = atlas_api("/entity/bulk", method="DELETE", params=params)
    return resp
