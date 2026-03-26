"""Tests for the bootstrap agent (all LLM calls mocked)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import numpy as np
import pytest

from sigint.bootstrap_agent import BootstrapAgent, BootstrapConfig, BootstrapState
from sigint.llm_backend import ColumnClassification, LLMResponse
from sigint.sampler import ColumnSample


# ── Helpers ──────────────────────────────────────────────────────


def _make_sample(name="col1", col_type="STRING", values=None):
    return ColumnSample(
        column_name=name,
        column_type=col_type,
        values=values or ["val1", "val2"],
    )


@dataclass
class _MockClassification:
    """Minimal mock for EmbeddingClassifier.classify() results."""
    category: MagicMock
    confidence: float
    conflict: float
    uncertainty_gap: float


def _mock_classifier(predictions: dict[str, tuple[str, float, float]]):
    """Create a mock EmbeddingClassifier.

    predictions: {column_name: (code, confidence, conflict)}
    """
    clf = MagicMock()

    def classify_side_effect(sample, siblings=None, **kwargs):
        name = sample.column_name
        if name not in predictions:
            return None
        code, conf, k = predictions[name]
        cat = MagicMock()
        cat.code = code
        cat.label = f"Label_{code}"
        result = _MockClassification(
            category=cat,
            confidence=conf,
            conflict=k,
            uncertainty_gap=k * 0.5,
        )
        return result

    clf.classify = MagicMock(side_effect=classify_side_effect)
    return clf


def _mock_category_set():
    cs = MagicMock()
    cs.name = "sigdg"

    def by_code_get(code, default=None):
        cat = MagicMock()
        cat.code = code
        cat.label = f"Label_{code}"
        return cat

    cs.by_code = MagicMock()
    cs.by_code.get = by_code_get
    cs.all_by_code = MagicMock()
    cs.all_by_code.get = by_code_get
    return cs


def _mock_backend(responses: list[list[ColumnClassification]]):
    """Create a mock LLM backend that returns pre-defined responses."""
    backend = MagicMock()
    call_count = [0]

    def classify_batch_side_effect(samples, siblings, system_prompt, revisit_context=None, **kwargs):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        classifications = responses[idx]
        return LLMResponse(
            classifications=classifications,
            input_tokens=100,
            output_tokens=50,
            model="test-model",
        )

    backend.classify_batch = MagicMock(side_effect=classify_batch_side_effect)
    return backend


def _make_agent(
    column_names: list[str],
    ml_predictions: dict[str, tuple[str, float, float]],
    llm_responses: list[list[ColumnClassification]],
    config: BootstrapConfig | None = None,
    embeddings: dict[str, np.ndarray] | None = None,
) -> BootstrapAgent:
    """Build a fully mocked BootstrapAgent."""
    cfg = config or BootstrapConfig(
        max_iterations=3,
        max_total_llm_calls=100,
        columns_per_call=5,
    )
    samples = {n: _make_sample(n) for n in column_names}
    siblings = {n: [] for n in column_names}

    return BootstrapAgent(
        config=cfg,
        llm_backend=_mock_backend(llm_responses),
        embedding_classifier=_mock_classifier(ml_predictions),
        category_set=_mock_category_set(),
        column_names=column_names,
        samples=samples,
        siblings_map=siblings,
        category_table="| Code | Label |\n|------|-------|",
        embeddings=embeddings,
    )


# ── Label propagation ────────────────────────────────────────────


class TestPropagateLabels:
    def test_propagates_to_similar_columns(self):
        names = ["source", "target"]
        # Create similar embeddings
        emb = np.random.RandomState(42).randn(384)
        emb /= np.linalg.norm(emb)
        embeddings = {
            "source": emb,
            "target": emb + np.random.RandomState(43).randn(384) * 0.01,  # very similar
        }
        # Normalize target too
        embeddings["target"] /= np.linalg.norm(embeddings["target"])

        agent = _make_agent(names, {
            "source": ("0085", 0.9, 0.01),
            "target": ("0085", 0.4, 0.1),  # ML agrees
        }, [[]], embeddings=embeddings)

        agent._run_ml_classification()
        agent._state.labels["source"] = "0085"
        agent._state.confidence["source"] = 0.95
        agent._state.label_source["source"] = "llm"

        propagated = agent._propagate_labels()
        assert "target" in propagated
        assert agent._state.labels["target"] == "0085"
        assert agent._state.label_source["target"] == "propagated"

    def test_skips_when_ml_disagrees(self):
        names = ["source", "target"]
        emb = np.ones(384) / np.sqrt(384)
        embeddings = {"source": emb, "target": emb}

        cfg = BootstrapConfig(confidence_floor=0.5)
        agent = _make_agent(names, {
            "source": ("0085", 0.9, 0.01),
            "target": ("0076", 0.8, 0.1),  # ML disagrees with high confidence
        }, [[]], config=cfg, embeddings=embeddings)

        agent._run_ml_classification()
        agent._state.labels["source"] = "0085"
        agent._state.confidence["source"] = 0.95
        agent._state.label_source["source"] = "llm"

        propagated = agent._propagate_labels()
        assert "target" not in propagated

    def test_no_propagation_without_embeddings(self):
        names = ["source", "target"]
        agent = _make_agent(names, {
            "source": ("0085", 0.9, 0.01),
            "target": ("0085", 0.4, 0.1),
        }, [[]])

        agent._state.labels["source"] = "0085"
        agent._state.label_source["source"] = "llm"
        propagated = agent._propagate_labels()
        assert propagated == []


# ── Disagreement detection ───────────────────────────────────────


class TestIdentifyDisagreements:
    def test_finds_high_k_disagreements(self):
        names = ["a", "b", "c"]
        agent = _make_agent(names, {
            "a": ("0085", 0.6, 0.35),  # high K
            "b": ("0076", 0.8, 0.05),  # low K → not a disagreement
            "c": ("0074", 0.5, 0.25),  # above threshold
        }, [[]])

        agent._run_ml_classification()
        # LLM gave different answers
        agent._state.labels = {"a": "0076", "b": "0076", "c": "0013"}

        disagreements = agent._identify_disagreements()
        assert "a" in disagreements  # ML=0085, LLM=0076, K=0.35
        assert "b" not in disagreements  # ML=0076, LLM=0076 (agree)
        assert "c" in disagreements  # ML=0074, LLM=0013, K=0.25

    def test_sorted_by_k_descending(self):
        names = ["a", "b"]
        agent = _make_agent(names, {
            "a": ("0085", 0.6, 0.25),
            "b": ("0076", 0.5, 0.35),
        }, [[]])

        agent._run_ml_classification()
        agent._state.labels = {"a": "0076", "b": "0013"}

        disagreements = agent._identify_disagreements()
        assert disagreements[0] == "b"  # K=0.35 > K=0.25


# ── Convergence check ────────────────────────────────────────────


class TestConvergence:
    def test_coverage_calculation(self):
        names = ["a", "b", "c", "d"]
        agent = _make_agent(names, {}, [[]])
        agent._state.labels = {"a": "0085", "b": "0076"}
        assert agent._coverage() == pytest.approx(0.5)

    def test_mean_k_calculation(self):
        names = ["a", "b"]
        agent = _make_agent(names, {}, [[]])
        agent._state.labels = {"a": "0085", "b": "0076"}
        agent._state.ml_conflict = {"a": 0.1, "b": 0.3}
        assert agent._mean_k() == pytest.approx(0.2)

    def test_coverage_empty(self):
        agent = _make_agent([], {}, [[]])
        assert agent._coverage() == 1.0

    def test_mean_k_no_labels(self):
        agent = _make_agent(["a"], {}, [[]])
        assert agent._mean_k() == 0.0


# ── Full loop ────────────────────────────────────────────────────


class TestFullLoop:
    def test_converges_when_llm_and_ml_agree(self):
        """LLM and ML agree → converges after Phase 2, no revisit needed."""
        names = ["a", "b", "c"]
        llm_response = [
            ColumnClassification("a", "0085", 0.95, "SSN pattern", []),
            ColumnClassification("b", "0076", 0.90, "email column", []),
            ColumnClassification("c", "0074", 0.88, "phone column", []),
        ]

        cfg = BootstrapConfig(
            max_iterations=3,
            max_total_llm_calls=100,
            columns_per_call=5,
            k_threshold=0.5,
            coverage_target=0.5,
            confidence_floor=0.3,
        )
        agent = _make_agent(
            names,
            {
                "a": ("0085", 0.7, 0.1),  # ML agrees, low K
                "b": ("0076", 0.6, 0.1),
                "c": ("0074", 0.5, 0.1),
            },
            [llm_response],
            config=cfg,
        )

        result = agent.run()
        assert result.ground_truth["a"] == "0085"
        assert result.ground_truth["b"] == "0076"
        assert result.ground_truth["c"] == "0074"
        assert result.converged
        assert result.llm_calls >= 1
        # No revisit iterations since ML agrees
        assert result.iterations == 0

    def test_revisit_on_disagreement(self):
        """LLM and ML disagree → Phase 3 revisit fires."""
        names = ["a", "b"]
        # Phase 1: LLM classifies
        llm_initial = [
            ColumnClassification("a", "0085", 0.95, "SSN", []),
            ColumnClassification("b", "0076", 0.90, "email", []),
        ]
        # Phase 3: revisit response (LLM sticks with its answer)
        llm_revisit = [
            ColumnClassification("a", "0085", 0.98, "confirmed SSN", []),
        ]

        cfg = BootstrapConfig(
            max_iterations=3,
            max_total_llm_calls=100,
            columns_per_call=5,
            k_threshold=0.15,  # Low enough that mean_k triggers revisit
            coverage_target=0.5,
            confidence_floor=0.3,
        )
        agent = _make_agent(
            names,
            {
                "a": ("0074", 0.7, 0.35),  # ML disagrees with LLM, high K
                "b": ("0076", 0.6, 0.05),  # ML agrees, low K
            },
            [llm_initial, llm_revisit],
            config=cfg,
        )

        result = agent.run()
        assert result.llm_calls >= 2  # Initial sweep + at least one revisit
        assert result.iterations >= 1  # At least one revisit iteration

    def test_budget_enforcement(self):
        """Agent stops when LLM call budget is exhausted."""
        names = [f"col_{i}" for i in range(20)]
        ml_preds = {n: ("0085", 0.3, 0.4) for n in names}  # All high K
        llm_resp = [
            ColumnClassification(n, "0085", 0.9, "test", []) for n in names[:5]
        ]

        cfg = BootstrapConfig(
            max_iterations=10,
            max_total_llm_calls=2,
            columns_per_call=5,
            k_threshold=0.1,
        )
        agent = _make_agent(names, ml_preds, [llm_resp], config=cfg)
        result = agent.run()
        assert result.llm_calls <= 2

    def test_output_json_format(self, tmp_path):
        """Ground truth JSON is compatible with --ground-truth."""
        import json

        names = ["a"]
        llm_resp = [ColumnClassification("a", "0085", 0.95, "test", [])]
        cfg = BootstrapConfig(
            max_iterations=1,
            max_total_llm_calls=100,
            columns_per_call=5,
            k_threshold=0.5,
            coverage_target=0.5,
            confidence_floor=0.3,
            output_path=str(tmp_path / "gt.json"),
        )
        agent = _make_agent(
            names,
            {"a": ("0085", 0.5, 0.1)},
            [llm_resp],
            config=cfg,
        )

        result = agent.run()
        path = agent.write_ground_truth(result)

        data = json.loads(path.read_text())
        assert isinstance(data, dict)
        assert "a" in data
        assert data["a"] == "0085"

    def test_ml_fallback_for_confident_columns(self):
        """Columns not labeled by LLM use ML prediction if confident."""
        names = ["llm_labeled", "ml_confident"]
        llm_resp = [
            ColumnClassification("llm_labeled", "0085", 0.95, "test", []),
            # LLM returns null for ml_confident
            ColumnClassification("ml_confident", None, 0.0, "unclear", []),
        ]

        cfg = BootstrapConfig(
            max_iterations=1,
            max_total_llm_calls=100,
            columns_per_call=5,
            k_threshold=0.5,
            coverage_target=0.5,
            confidence_floor=0.5,
        )
        agent = _make_agent(
            names,
            {
                "llm_labeled": ("0085", 0.5, 0.1),
                "ml_confident": ("0076", 0.8, 0.05),  # confident ML
            },
            [llm_resp],
            config=cfg,
        )

        result = agent.run()
        # ML confident column should be in GT via fallback
        assert "ml_confident" in result.ground_truth
        assert result.source_map.get("ml_confident") == "ml"

    def test_token_tracking(self):
        """Token counts are accumulated across calls."""
        names = ["a"]
        llm_resp = [ColumnClassification("a", "0085", 0.95, "test", [])]
        cfg = BootstrapConfig(
            max_iterations=1, max_total_llm_calls=100,
            columns_per_call=5,
            k_threshold=0.5, coverage_target=0.5, confidence_floor=0.3,
        )
        agent = _make_agent(
            names, {"a": ("0085", 0.5, 0.1)}, [llm_resp], config=cfg,
        )
        result = agent.run()
        assert result.tokens_input > 0
        assert result.tokens_output > 0

    def test_all_columns_sent_to_llm_in_phase1(self):
        """Phase 1 sends ALL columns, not a subset."""
        names = ["a", "b", "c", "d", "e"]
        llm_resp = [
            ColumnClassification(n, "0085", 0.90, "test", []) for n in names
        ]

        cfg = BootstrapConfig(
            max_iterations=1,
            max_total_llm_calls=100,
            columns_per_call=2,  # Small chunks to verify all are sent
            k_threshold=0.5,
            coverage_target=0.5,
            confidence_floor=0.3,
        )
        agent = _make_agent(
            names,
            {n: ("0085", 0.5, 0.05) for n in names},
            [llm_resp],
            config=cfg,
        )

        result = agent.run()
        # All 5 columns should be labeled after Phase 1
        assert len(result.ground_truth) == 5
        # 5 columns / 2 per call = 3 LLM calls minimum
        assert result.llm_calls >= 3
