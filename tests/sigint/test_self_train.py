"""Tests for self-training configuration and pipeline integration."""

from __future__ import annotations

from sigint.config import PipelineConfig, _HOCON_MAP


class TestSelfTrainConfig:
    """Verify self-training config keys exist and have correct defaults."""

    def test_self_train_default_false(self):
        cfg = PipelineConfig()
        assert cfg.self_train is False

    def test_self_train_rounds_default(self):
        cfg = PipelineConfig()
        assert cfg.self_train_rounds == 1

    def test_self_train_threshold_default(self):
        cfg = PipelineConfig()
        assert cfg.self_train_threshold == 0.80

    def test_self_train_hocon_mapping(self):
        assert "ml.self_train" in _HOCON_MAP
        field_name, field_type = _HOCON_MAP["ml.self_train"]
        assert field_name == "self_train"
        assert field_type is bool

    def test_self_train_rounds_hocon_mapping(self):
        assert "ml.self_train_rounds" in _HOCON_MAP
        field_name, field_type = _HOCON_MAP["ml.self_train_rounds"]
        assert field_name == "self_train_rounds"
        assert field_type is int

    def test_self_train_threshold_hocon_mapping(self):
        assert "ml.self_train_threshold" in _HOCON_MAP
        field_name, field_type = _HOCON_MAP["ml.self_train_threshold"]
        assert field_name == "self_train_threshold"
        assert field_type is float

    def test_self_train_override(self):
        cfg = PipelineConfig(self_train=True, self_train_rounds=3)
        assert cfg.self_train is True
        assert cfg.self_train_rounds == 3
