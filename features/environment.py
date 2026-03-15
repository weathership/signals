"""Behave environment hooks — NO SILENT SKIPS.

All tests (tier-0 and tier-1) require the full devenv stack. If the stack
is not healthy, before_all asserts immediately. There is no "offline"
mode — run 'devenv up' before running tests.

After process-compose health passes, we verify application-level
readiness (Atlas API responds, Impala accepts queries) before tests run.
"""

import logging
import os
import sys
import time

import requests

log = logging.getLogger("signals.bdd")

# All processes that must be healthy for ANY test
REQUIRED_PROCESSES = [
    "postgres",
    "kdc",
    "atlas",
    "kudu-master",
    "kudu-tserver",
    "impala-statestore",
    "impala-catalogd",
    "impala-impalad",
]

# Application-level readiness checks with retry
APP_READY_TIMEOUT = 120  # seconds
APP_READY_INTERVAL = 5   # seconds between retries


def _wait_for(description, check_fn, timeout, interval):
    """Retry check_fn until it returns True or timeout expires.

    check_fn should return True on success, or a string describing the error.
    """
    deadline = time.time() + timeout
    last_error = "no attempts"
    while time.time() < deadline:
        try:
            result = check_fn()
            if result is True:
                log.info("%s: ready", description)
                return
            last_error = result  # error description string
        except Exception as e:
            last_error = str(e)
        time.sleep(interval)
    assert False, f"{description} not ready after {timeout}s: {last_error}"


def _check_atlas_api():
    """Check Atlas admin API responds with ACTIVE status."""
    resp = requests.get(
        "http://localhost:21000/api/atlas/admin/status",
        auth=("admin", "admin"), timeout=5,
    )
    if resp.status_code == 200:
        data = resp.json()
        status = data.get("Status") or data.get("status")
        if status == "ACTIVE":
            return True
        return f"status={status}"
    return f"HTTP {resp.status_code}"


def _check_impala():
    """Check Impala accepts SQL queries."""
    # Thrift C accelerator blocked in helpers.py; ensure it's blocked here too
    sys.modules.setdefault("thrift.protocol.fastbinary", None)
    sys.modules.setdefault("thrift.protocol.fastproto", None)
    from impala.dbapi import connect

    conn = connect(host="localhost", port=21050, auth_mechanism="NOSASL")
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    conn.close()
    if result and result[0] == 1:
        return True
    return f"unexpected result: {result}"


def before_all(context):
    """Global test setup — assert full stack health.

    Two phases:
    1. Process-compose: all required processes are running/ready
    2. Application: key services accept requests (Atlas API, Impala SQL)
    """
    context.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    context.config.setup_logging()

    # ── Phase 1: Process-compose health ─────────────────────────────────
    sys.path.insert(0, os.path.join(context.project_root, "scripts"))
    from wait_for_stack import find_socket, get_processes

    socket_path = find_socket()
    assert socket_path, (
        "No process-compose socket found. Run 'devenv up' first, "
        "or use 'devenv test' which starts the stack automatically."
    )

    procs = get_processes(socket_path)
    assert procs, (
        "process-compose not responding on socket. "
        "Check 'devenv up' output for errors."
    )

    proc_map = {p["name"]: p for p in procs}
    unhealthy = []
    for name in REQUIRED_PROCESSES:
        proc = proc_map.get(name)
        if not proc:
            unhealthy.append(f"{name}: missing")
        elif proc.get("has_ready_probe") and proc.get("is_ready") != "Ready":
            unhealthy.append(f"{name}: {proc.get('status', 'unknown')} (not ready)")
        elif not proc.get("has_ready_probe") and proc.get("status") != "Running":
            unhealthy.append(f"{name}: {proc.get('status', 'unknown')}")

    assert not unhealthy, (
        "Stack not fully healthy — ALL tests require ALL services:\n  "
        + "\n  ".join(unhealthy)
        + "\n\nRun 'devenv up' and wait for all services to be ready."
    )

    healthy_names = [p["name"] for p in procs if p.get("is_ready") == "Ready"]
    log.info("Full stack healthy: %s", ", ".join(healthy_names))

    # ── Phase 2: Application-level readiness ────────────────────────────
    log.info(
        "Waiting up to %ds for application-level readiness...",
        APP_READY_TIMEOUT,
    )
    _wait_for("Atlas API", _check_atlas_api, APP_READY_TIMEOUT, APP_READY_INTERVAL)
    _wait_for("Impala SQL", _check_impala, APP_READY_TIMEOUT, APP_READY_INTERVAL)

    log.info("All readiness checks passed — running tests")


def before_scenario(context, scenario):
    """Per-scenario setup."""
    pass


def after_scenario(context, scenario):
    """Per-scenario cleanup."""
    pass
