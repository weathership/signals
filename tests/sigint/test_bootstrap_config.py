"""Tests for bootstrap agent configuration (HOCON mapping + defaults)."""

from __future__ import annotations

import pytest

from sigint.config import PipelineConfig, _HOCON_MAP, load_config


class TestBootstrapConfigDefaults:
    """Verify PipelineConfig has correct default values for bootstrap fields."""

    def test_max_iterations(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_max_iterations == 5

    def test_k_threshold(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_k_threshold == 0.2

    def test_uncertainty_gap_threshold(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_uncertainty_gap_threshold == 0.3

    def test_coverage_target(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_coverage_target == 0.95

    def test_confidence_floor(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_confidence_floor == 0.5

    def test_initial_sample_fraction(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_initial_sample_fraction == 0.3

    def test_propagation_similarity(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_propagation_similarity == 0.85

    def test_max_llm_calls_per_iteration(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_max_llm_calls_per_iteration == 500

    def test_max_total_llm_calls(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_max_total_llm_calls == 5000

    def test_columns_per_call(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_columns_per_call == 50

    def test_output(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_output == "build/bootstrap_gt.json"

    def test_llm_backend(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_llm_backend == "cerebras"

    def test_llm_api_key_default_none(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_llm_api_key is None

    def test_llm_base_url_default_none(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_llm_base_url is None

    def test_llm_model(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_llm_model == "claude-opus-4-6"

    def test_llm_discount(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_llm_discount == 0.10

    def test_table_aware_batching_default(self):
        cfg = PipelineConfig()
        assert cfg.bootstrap_table_aware_batching is True


class TestBootstrapHoconMapping:
    """Verify all bootstrap HOCON paths exist in _HOCON_MAP."""

    EXPECTED_KEYS = [
        "bootstrap.max_iterations",
        "bootstrap.k_threshold",
        "bootstrap.uncertainty_gap_threshold",
        "bootstrap.coverage_target",
        "bootstrap.confidence_floor",
        "bootstrap.initial_sample_fraction",
        "bootstrap.propagation_similarity",
        "bootstrap.max_llm_calls_per_iteration",
        "bootstrap.max_total_llm_calls",
        "bootstrap.columns_per_call",
        "bootstrap.output",
        "bootstrap.llm_backend",
        "bootstrap.llm_api_key",
        "bootstrap.llm_base_url",
        "bootstrap.llm_model",
        "bootstrap.llm_discount",
        "bootstrap.table_aware_batching",
    ]

    @pytest.mark.parametrize("hocon_key", EXPECTED_KEYS)
    def test_hocon_key_exists(self, hocon_key):
        assert hocon_key in _HOCON_MAP, f"Missing HOCON mapping: {hocon_key}"

    @pytest.mark.parametrize("hocon_key", EXPECTED_KEYS)
    def test_hocon_field_exists_on_config(self, hocon_key):
        field_name, _ = _HOCON_MAP[hocon_key]
        cfg = PipelineConfig()
        assert hasattr(cfg, field_name), f"PipelineConfig missing field: {field_name}"


class TestBootstrapConfigLoading:
    """Verify bootstrap config loads from base.conf."""

    def test_loads_defaults_from_hocon(self):
        cfg = load_config()
        assert cfg.bootstrap_max_iterations == 5
        assert cfg.bootstrap_k_threshold == 0.2
        assert cfg.bootstrap_llm_backend == "cerebras"

    def test_cli_overrides_bootstrap(self):
        cfg = load_config(overrides={
            "bootstrap_max_iterations": 10,
            "bootstrap_k_threshold": 0.3,
        })
        assert cfg.bootstrap_max_iterations == 10
        assert cfg.bootstrap_k_threshold == 0.3
