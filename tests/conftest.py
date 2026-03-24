"""Preflight configuration check.

Validates that build/config/sigint.env exists and contains all required
keys before any test runs. This ensures the HOCON config has been resolved
(``just resolve-config``) and all necessary values are provided.

The check runs once per session. If the materialized config is missing,
it is auto-generated from config/base.conf defaults so that tests work
out of the box for benchmarking. Validation errors for conditional keys
(e.g. ANTHROPIC_API_KEY when classifier_type=llm) are reported as
warnings, not failures — unit tests don't need live service credentials.
"""

from __future__ import annotations

import pytest

from sigint.config import (
    _MATERIALIZED_PATH,
    load_config,
    materialize_config,
    preflight_gpu,
    validate_materialized_config,
)


@pytest.fixture(scope="session", autouse=True)
def preflight_config():
    """Ensure materialized config exists and validate required keys.

    If build/config/sigint.env does not exist, materializes it from
    config/base.conf defaults (sufficient for benchmark/test mode).
    """
    if not _MATERIALIZED_PATH.exists():
        cfg = load_config()
        materialize_config(cfg, _MATERIALIZED_PATH)

    errors = validate_materialized_config(_MATERIALIZED_PATH)
    if errors:
        msg = "Preflight config validation errors:\n" + "\n".join(
            f"  - {e}" for e in errors
        )
        pytest.fail(msg, pytrace=False)


@pytest.fixture(scope="session", autouse=True)
def preflight_gpu_check():
    """Detect GPU availability and warn about CUDA version mismatches.

    This is informational — GPU issues produce warnings, not failures,
    because the pipeline always falls back to CPU.
    """
    gpu = preflight_gpu()
    for w in gpu.warnings:
        import warnings
        warnings.warn(w, stacklevel=1)
