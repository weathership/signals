"""Behave environment hooks — tier-aware scenario filtering.

Tier system (same split as synth and other constellation projects):
  tests/     — pytest units
  features/  — behave BDD

  @tier-0  Pure Python, no external services. Runs anywhere (CI, local).
  @tier-1  Full devenv stack (PG, KDC, Atlas, Kudu, Impala). Opt in with
           SIGNALS_BDD_TIER1=1 (default skip so `just behave` stays hermetic).
  @tier-2/3  Not yet implemented — auto-skipped.

Tier-1 scenarios verify process-compose health and application readiness
before running (cached per session so the check happens only once).
"""

import logging
import os
import sys
import time

log = logging.getLogger("signals.bdd")

# All processes that must be healthy for tier-1 tests
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


def _tier_from_scenario(scenario):
    """Extract the highest tier from a scenario's tags."""
    tiers = []
    for tag in list(scenario.tags) + list(scenario.feature.tags):
        if tag.startswith("tier-"):
            try:
                tiers.append(int(tag.split("-")[1]))
            except (IndexError, ValueError):
                pass
    return max(tiers) if tiers else 0


def _wait_for(description, check_fn, timeout, interval):
    """Retry check_fn until it returns True or timeout expires."""
    deadline = time.time() + timeout
    last_error = "no attempts"
    while time.time() < deadline:
        try:
            result = check_fn()
            if result is True:
                log.info("%s: ready", description)
                return
            last_error = result
        except Exception as e:
            last_error = str(e)
        time.sleep(interval)
    assert False, f"{description} not ready after {timeout}s: {last_error}"


def _check_atlas_api():
    """Check Atlas admin API responds with ACTIVE status."""
    import requests

    resp = requests.get(
        "http://localhost:21010/api/atlas/admin/status",
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


def _ensure_stack_healthy(context):
    """One-time stack health check, cached on context._stack_verified."""
    if getattr(context, "_stack_verified", False):
        return

    log.info("Tier-1 scenario — verifying devenv stack health...")

    # Phase 1: Process-compose health
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
            unhealthy.append(
                f"{name}: {proc.get('status', 'unknown')} (not ready)"
            )
        elif not proc.get("has_ready_probe") and proc.get("status") != "Running":
            unhealthy.append(f"{name}: {proc.get('status', 'unknown')}")

    assert not unhealthy, (
        "Stack not fully healthy — tier-1 tests require ALL services:\n  "
        + "\n  ".join(unhealthy)
        + "\n\nRun 'devenv up' and wait for all services to be ready."
    )

    healthy_names = [p["name"] for p in procs if p.get("is_ready") == "Ready"]
    log.info("Full stack healthy: %s", ", ".join(healthy_names))

    # Phase 2: Application-level readiness
    log.info(
        "Waiting up to %ds for application-level readiness...",
        APP_READY_TIMEOUT,
    )
    _wait_for("Atlas API", _check_atlas_api, APP_READY_TIMEOUT, APP_READY_INTERVAL)
    _wait_for("Impala SQL", _check_impala, APP_READY_TIMEOUT, APP_READY_INTERVAL)

    log.info("All readiness checks passed")
    context._stack_verified = True


def before_all(context):
    """Global test setup — set project root and logging only."""
    context.project_root = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    context.config.setup_logging()


def before_scenario(context, scenario):
    """Per-scenario setup — tier-aware stack verification."""
    tier = _tier_from_scenario(scenario)

    if tier >= 2:
        scenario.skip(f"tier-{tier} not yet implemented")
        return

    if tier >= 1:
        if not os.environ.get("SIGNALS_BDD_TIER1"):
            scenario.skip(
                "tier-1 needs devenv services — set SIGNALS_BDD_TIER1=1 "
                "(and run 'devenv up')"
            )
            return
        _ensure_stack_healthy(context)


def after_scenario(context, scenario):
    """Per-scenario cleanup — best-effort removal of test entities."""
    from features.platform.steps.helpers import (
        delete_atlas_entities_by_guids,
        delete_atlas_entity,
        impala_execute,
        table_qualified_name,
    )

    # Clean up Atlas entities from bridge registration
    if hasattr(context, "atlas_registration"):
        try:
            reg = context.atlas_registration
            col_guids = list(reg.get("column_guids", {}).values())
            if col_guids:
                delete_atlas_entities_by_guids(col_guids)
            if reg.get("table_guid"):
                delete_atlas_entities_by_guids([reg["table_guid"]])
        except Exception:
            pass

    # Clean up PII-tagged tables from classification search tests
    if hasattr(context, "pii_tagged_tables"):
        for table in context.pii_tagged_tables:
            try:
                qn = table_qualified_name(table)
                delete_atlas_entity("rdbms_table", qn)
            except Exception:
                pass
            try:
                impala_execute(f"DROP TABLE IF EXISTS {table}")
            except Exception:
                pass

    # Clean up last-created Impala table
    if hasattr(context, "last_created_table"):
        try:
            impala_execute(f"DROP TABLE IF EXISTS {context.last_created_table}")
        except Exception:
            pass

    # Clean up temp files created by classification tests
    if hasattr(context, "_temp_files"):
        import pathlib

        for p in context._temp_files:
            try:
                pathlib.Path(p).unlink(missing_ok=True)
            except Exception:
                pass
