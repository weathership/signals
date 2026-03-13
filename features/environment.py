"""Behave environment hooks for signals-360 BDD tests.

Tier system (inspired by gaius):
  Tier 0: Pure unit — no external dependencies
  Tier 1: Services — requires PostgreSQL + KDC (devenv up)
  Tier 2: Engine   — requires gRPC engine running
  Tier 3: Full     — requires all services + engine + visualization stack
"""

import os
import logging

log = logging.getLogger("signals.bdd")

# Tags that require infrastructure
INFRA_TAGS = {
    "db-required": "PostgreSQL",
    "kdc-required": "Kerberos KDC",
    "engine-required": "gRPC engine",
    "viz-required": "Visualization stack",
    "kudu-required": "Kudu cluster",
    "impala-required": "Impala query engine",
    "polaris-required": "Polaris Iceberg catalog",
}


def before_all(context):
    """Global test setup."""
    context.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    context.config.setup_logging()


def before_scenario(context, scenario):
    """Per-scenario setup with tag-based skipping."""
    tags = set(scenario.effective_tags)

    for tag, service_name in INFRA_TAGS.items():
        if tag in tags:
            if not _check_service(tag):
                scenario.skip(f"{service_name} not available")
                return


def after_scenario(context, scenario):
    """Per-scenario cleanup."""
    pass


def _check_service(tag):
    """Check if a required service is available."""
    # Placeholder — will be implemented as services come online
    return False
