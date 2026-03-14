"""Shared helpers for BDD step implementations."""

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

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def pg_conn(dbname="signals"):
    """Connect to a local PostgreSQL database."""
    return psycopg.connect(host="localhost", port=5455, dbname=dbname, autocommit=True)


def impala_conn():
    """Connect to Impala via HiveServer2 (no auth)."""
    return impala_connect(host="localhost", port=21050, auth_mechanism="NOSASL")


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
    url = f"http://localhost:21000/api/atlas/v2{path}"
    return requests.request(method, url, auth=("admin", "admin"), timeout=10, **kwargs)


def atlas_admin_api(path, method="GET", **kwargs):
    """Call the Atlas admin REST API."""
    url = f"http://localhost:21000/api/atlas{path}"
    return requests.request(method, url, auth=("admin", "admin"), timeout=10, **kwargs)


def atlas_api_json(path, method="GET", **kwargs):
    """Call Atlas v2 API and return parsed JSON (raises on non-2xx)."""
    resp = atlas_api(path, method=method, **kwargs)
    resp.raise_for_status()
    return resp.json()


def kudu_master_api(path):
    """Call the Kudu master HTTP API."""
    return requests.get(f"http://localhost:8051{path}", timeout=10)


def run_cmd(cmd, **kwargs):
    """Run a shell command with standard timeout and capture."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kwargs)
