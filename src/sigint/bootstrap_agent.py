"""Bootstrap agent: LLM-driven classification for novel tables.

Two-phase architecture optimized for fast LLM backends (Cerebras, etc.):

  Phase 1 — LLM sweep:
    Send ALL columns to the LLM in one batch sweep.  LLMs are strong
    zero-shot classifiers; the vast majority of labels will be correct.

  Phase 2 — ML validation:
    Run the ML pipeline (cosine + pattern + name_match) once using LLM
    labels as pseudo-GT.  DST conflict K identifies columns where ML
    evidence disagrees with the LLM label.

  Phase 3 — Targeted revisit:
    Re-send only high-K disagreement columns to the LLM with enriched
    ML context (prediction, belief interval, confusable pair).  Iterate
    on this shrinking set until K converges or budget is exhausted.

This avoids re-classifying settled records.  The LLM processes each
column at most twice (initial + revisit), and the ML pipeline runs
at most 2-3 times total.

Output: ground truth JSON compatible with --ground-truth / --self-train.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from sigint.data_element import DataElementCatalog
from sigint.llm_backend import (
    LLMBackend,
    ColumnClassification,
    build_batch_user_prompt,
    build_system_prompt,
)
from sigint.sampler import ColumnSample

logger = logging.getLogger(__name__)


# ── State types ──────────────────────────────────────────────────


@dataclass
class BootstrapConfig:
    """Bootstrap agent configuration."""

    max_iterations: int = 5
    k_threshold: float = 0.2
    uncertainty_gap_threshold: float = 0.3
    coverage_target: float = 0.95
    confidence_floor: float = 0.5
    initial_sample_fraction: float = 0.3
    propagation_similarity_threshold: float = 0.85
    max_llm_calls_per_iteration: int = 500
    max_total_llm_calls: int = 5000
    columns_per_call: int = 50
    output_path: str = "build/bootstrap_gt.json"
    llm_discount: float = 0.10


@dataclass
class BootstrapState:
    """Mutable state across bootstrap phases."""

    iteration: int = 0
    labels: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    label_source: dict[str, str] = field(default_factory=dict)
    ml_prediction: dict[str, str] = field(default_factory=dict)
    ml_confidence: dict[str, float] = field(default_factory=dict)
    ml_conflict: dict[str, float] = field(default_factory=dict)
    ml_uncertainty: dict[str, float] = field(default_factory=dict)
    llm_calls_total: int = 0
    tokens_input: int = 0
    tokens_output: int = 0


@dataclass(frozen=True)
class BootstrapResult:
    """Final output of the bootstrap agent."""

    ground_truth: dict[str, str]
    confidence_map: dict[str, float]
    source_map: dict[str, str]
    converged: bool
    final_coverage: float
    final_mean_k: float
    iterations: int
    llm_calls: int
    tokens_input: int
    tokens_output: int


# ── Agent ────────────────────────────────────────────────────────


class BootstrapAgent:
    """LLM bootstrap agent with 2-phase sweep + targeted revisit.

    Args:
        config: Bootstrap configuration.
        llm_backend: Configured LLM backend (Anthropic, Cerebras, etc.).
        embedding_classifier: Pre-initialized EmbeddingClassifier instance.
        category_set: Taxonomy category set.
        column_names: List of all column names to classify.
        samples: Pre-built ColumnSample per column name.
        siblings_map: Sibling columns per column name.
        category_table: Markdown table for system prompt.
        embeddings: Optional pre-computed embeddings for propagation.
    """

    def __init__(
        self,
        config: BootstrapConfig,
        llm_backend: LLMBackend,
        embedding_classifier,
        category_set,
        column_names: list[str],
        samples: dict[str, ColumnSample],
        siblings_map: dict[str, list[ColumnSample]],
        category_table: str,
        embeddings: dict[str, Any] | None = None,
        column_table: dict[str, str] | None = None,
        data_elements: DataElementCatalog | None = None,
    ) -> None:
        self._config = config
        self._backend = llm_backend
        self._classifier = embedding_classifier
        self._category_set = category_set
        self._column_names = column_names
        self._samples = samples
        self._siblings_map = siblings_map
        self._system_prompt = build_system_prompt(category_table)
        self._embeddings = embeddings or {}
        self._column_table = column_table or {}
        self._data_elements = data_elements
        self._state = BootstrapState()

    def run(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> BootstrapResult:
        """Execute the 2-phase bootstrap classification.

        Phase 1: LLM sweep — classify all columns via LLM.
        Phase 2: ML validation — run ML pipeline, identify disagreements.
        Phase 3: Targeted revisit — re-classify only high-K columns.
        """
        cfg = self._config
        state = self._state

        def _report(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        # ── Phase 1: LLM sweep ───────────────────────────────────
        all_columns = list(self._column_names)
        _report(
            f"Phase 1: LLM sweep — classifying {len(all_columns)} columns "
            f"({(len(all_columns) + cfg.columns_per_call - 1) // cfg.columns_per_call} calls)"
        )
        self._llm_classify_batch(all_columns)

        # Propagate to any columns the LLM returned null for
        propagated = self._propagate_labels()
        coverage = self._coverage()
        _report(
            f"  LLM labeled {len(state.labels)}/{len(all_columns)} columns "
            f"(coverage={coverage:.1%}, propagated={len(propagated)}, "
            f"calls={state.llm_calls_total})"
        )

        # ── Phase 2: ML validation ───────────────────────────────
        _report("Phase 2: ML validation — computing DST conflict K")
        self._run_ml_classification()
        disagreements = self._identify_disagreements()
        mean_k = self._mean_k()
        _report(
            f"  ML validation: mean K={mean_k:.3f}, "
            f"disagreements={len(disagreements)}"
        )

        # ── Phase 3: Targeted revisit ────────────────────────────
        for iteration in range(1, cfg.max_iterations + 1):
            if not disagreements:
                _report("  No disagreements — converged")
                break

            if state.llm_calls_total >= cfg.max_total_llm_calls:
                _report(f"  Budget exhausted ({state.llm_calls_total} calls)")
                break

            if mean_k < cfg.k_threshold:
                _report(f"  Mean K={mean_k:.3f} < threshold — converged")
                break

            state.iteration = iteration
            _report(
                f"Revisit {iteration}: re-classifying {len(disagreements)} "
                f"high-K columns with ML context"
            )
            self._llm_revisit(disagreements)

            # Re-validate only the revisited columns against ML
            self._run_ml_classification()
            disagreements = self._identify_disagreements()
            mean_k = self._mean_k()
            coverage = self._coverage()
            _report(
                f"  After revisit: mean K={mean_k:.3f}, "
                f"disagreements={len(disagreements)}, "
                f"coverage={coverage:.1%}, "
                f"LLM calls={state.llm_calls_total}"
            )

        # ── Build result ─────────────────────────────────────────
        coverage = self._coverage()
        mean_k = self._mean_k()
        converged = coverage >= cfg.coverage_target and mean_k < cfg.k_threshold

        # For columns without LLM labels, use ML prediction if confident
        gt = dict(state.labels)
        for name in self._column_names:
            if name not in gt and state.ml_confidence.get(name, 0) >= cfg.confidence_floor:
                gt[name] = state.ml_prediction[name]
                state.confidence[name] = state.ml_confidence[name]
                state.label_source[name] = "ml"

        _report(
            f"Bootstrap complete: {len(gt)}/{len(self._column_names)} columns labeled, "
            f"converged={converged}, mean K={mean_k:.3f}, "
            f"LLM calls={state.llm_calls_total}"
        )

        return BootstrapResult(
            ground_truth=gt,
            confidence_map=dict(state.confidence),
            source_map=dict(state.label_source),
            converged=converged,
            final_coverage=coverage,
            final_mean_k=mean_k,
            iterations=state.iteration,
            llm_calls=state.llm_calls_total,
            tokens_input=state.tokens_input,
            tokens_output=state.tokens_output,
        )

    # ── ML classification ────────────────────────────────────────

    def _run_ml_classification(self) -> None:
        """Run embedding classifier on all columns, store K per column."""
        state = self._state
        for name in self._column_names:
            sample = self._samples[name]
            siblings = self._siblings_map.get(name)
            result = self._classifier.classify(sample, siblings)
            if result is not None:
                state.ml_prediction[name] = result.category.code
                state.ml_confidence[name] = result.confidence
                state.ml_conflict[name] = getattr(result, "conflict", 0.0)
                state.ml_uncertainty[name] = getattr(result, "uncertainty_gap", 0.0)

    # ── LLM classification ───────────────────────────────────────

    def _llm_classify_batch(self, column_names: list[str]) -> None:
        """Send columns to LLM in table-aware batches and update state.

        When ``column_table`` is populated, columns are grouped by table so
        the LLM sees coherent table context.  Within each table, chunks of
        ``columns_per_call`` are sent.  Falls back to flat batching when no
        table mapping is available.
        """
        cfg = self._config
        state = self._state

        # Group by table for coherent LLM context
        by_table: dict[str, list[str]] = {}
        for name in column_names:
            table = self._column_table.get(name, "__flat__")
            by_table.setdefault(table, []).append(name)

        for table_name, table_cols in by_table.items():
            for i in range(0, len(table_cols), cfg.columns_per_call):
                if state.llm_calls_total >= cfg.max_total_llm_calls:
                    return

                chunk = table_cols[i: i + cfg.columns_per_call]
                self._classify_chunk(chunk, table_name=table_name)

    def _classify_chunk(
        self,
        chunk: list[str],
        table_name: str | None = None,
        revisit_context: dict[str, dict] | None = None,
    ) -> None:
        """Classify a single chunk of columns via LLM."""
        state = self._state
        samples = [self._samples[n] for n in chunk]
        siblings = {n: self._siblings_map.get(n, []) for n in chunk}

        # Resolve data elements for this table
        de_list = None
        if self._data_elements and table_name and table_name != "__flat__":
            de_list = self._data_elements.for_table(table_name) or None

        # Build prompt with table and data element context
        user_prompt = build_batch_user_prompt(
            samples, siblings,
            revisit_context=revisit_context,
            table_name=table_name if table_name != "__flat__" else None,
            data_elements=de_list,
        )

        try:
            response = self._backend.classify_batch(
                samples, siblings, self._system_prompt,
                revisit_context=revisit_context,
                _user_prompt_override=user_prompt,
            )
        except Exception as e:
            logger.warning("LLM call failed: %s", e)
            return

        state.llm_calls_total += 1
        state.tokens_input += response.input_tokens
        state.tokens_output += response.output_tokens

        source = "llm_revisit" if revisit_context else "llm"
        self._apply_classifications(response.classifications, source=source)

    def _apply_classifications(
        self,
        classifications: list[ColumnClassification],
        source: str,
    ) -> None:
        """Apply LLM classifications to state."""
        state = self._state
        for c in classifications:
            if c.category_code and c.confidence > 0:
                state.labels[c.column_name] = c.category_code
                state.confidence[c.column_name] = c.confidence
                state.label_source[c.column_name] = source

    # ── Label propagation ────────────────────────────────────────

    def _propagate_labels(self) -> list[str]:
        """Propagate LLM-direct labels to similar unlabeled columns.

        Only propagates from LLM-direct labels (not previously propagated).
        Skips if ML strongly disagrees.

        Returns list of newly labeled column names.
        """
        if not self._embeddings:
            return []

        cfg = self._config
        state = self._state
        threshold = cfg.propagation_similarity_threshold

        # Source columns: only LLM-direct labels
        llm_direct = [
            n for n in state.labels
            if state.label_source.get(n) == "llm"
        ]
        if not llm_direct:
            return []

        unlabeled = [n for n in self._column_names if n not in state.labels]
        if not unlabeled:
            return []

        propagated = []
        for source_name in llm_direct:
            source_emb = self._embeddings.get(source_name)
            if source_emb is None:
                continue

            source_code = state.labels[source_name]

            for target_name in unlabeled:
                if target_name in state.labels:
                    continue  # Already labeled in this pass
                target_emb = self._embeddings.get(target_name)
                if target_emb is None:
                    continue

                sim = float(np.dot(source_emb, target_emb))
                if sim < threshold:
                    continue

                # Skip if ML strongly disagrees
                ml_code = state.ml_prediction.get(target_name)
                ml_conf = state.ml_confidence.get(target_name, 0)
                if ml_code and ml_code != source_code and ml_conf > cfg.confidence_floor:
                    continue

                state.labels[target_name] = source_code
                state.confidence[target_name] = sim * state.confidence.get(source_name, 0.5)
                state.label_source[target_name] = "propagated"
                propagated.append(target_name)

        return propagated

    # ── Disagreement detection ───────────────────────────────────

    def _identify_disagreements(self) -> list[str]:
        """Find columns where LLM and ML disagree AND K is high.

        Returns column names sorted by K descending.
        """
        cfg = self._config
        state = self._state
        disagreements = []

        for name in self._column_names:
            llm_code = state.labels.get(name)
            ml_code = state.ml_prediction.get(name)
            k = state.ml_conflict.get(name, 0)

            if (
                llm_code
                and ml_code
                and llm_code != ml_code
                and k > cfg.k_threshold
            ):
                disagreements.append(name)

        disagreements.sort(key=lambda n: -state.ml_conflict.get(n, 0))
        return disagreements

    # ── LLM revisit ──────────────────────────────────────────────

    def _llm_revisit(self, column_names: list[str]) -> None:
        """Re-classify columns with enriched ML context."""
        cfg = self._config
        state = self._state

        revisit_context: dict[str, dict] = {}
        for name in column_names:
            ml_code = state.ml_prediction.get(name, "")
            ml_label = ""
            cat = self._category_set.by_code.get(ml_code) or self._category_set.all_by_code.get(ml_code)
            if cat:
                ml_label = getattr(cat, "label", ml_code)

            # Find confusable pair if applicable
            llm_code = state.labels.get(name, "")
            llm_label = ""
            llm_cat = self._category_set.by_code.get(llm_code) or self._category_set.all_by_code.get(llm_code)
            if llm_cat:
                llm_label = getattr(llm_cat, "label", llm_code)

            confusable = f"{ml_label} / {llm_label}" if ml_label and llm_label else ""

            revisit_context[name] = {
                "ml_prediction": ml_label or ml_code,
                "belief": 0.0,  # Would need frame access for exact values
                "plausibility": 0.0,
                "conflict": state.ml_conflict.get(name, 0),
                "confusable": confusable,
                "previous": {
                    "code": llm_code,
                    "confidence": state.confidence.get(name, 0),
                },
            }

        # Group by table for coherent revisit context
        by_table: dict[str, list[str]] = {}
        for name in column_names:
            table = self._column_table.get(name, "__flat__")
            by_table.setdefault(table, []).append(name)

        for table_name, table_cols in by_table.items():
            for i in range(0, len(table_cols), cfg.columns_per_call):
                if state.llm_calls_total >= cfg.max_total_llm_calls:
                    return

                chunk = table_cols[i: i + cfg.columns_per_call]
                chunk_context = {n: revisit_context[n] for n in chunk}
                self._classify_chunk(
                    chunk,
                    table_name=table_name,
                    revisit_context=chunk_context,
                )

    # ── Metrics ──────────────────────────────────────────────────

    def _coverage(self) -> float:
        """Fraction of columns with a label (LLM, propagated, or ML)."""
        if not self._column_names:
            return 1.0
        labeled = sum(
            1 for n in self._column_names
            if n in self._state.labels
        )
        return labeled / len(self._column_names)

    def _mean_k(self) -> float:
        """Mean DST conflict K across all labeled columns."""
        state = self._state
        labeled = [n for n in self._column_names if n in state.labels]
        if not labeled:
            return 0.0
        return sum(state.ml_conflict.get(n, 0) for n in labeled) / len(labeled)

    # ── Output ───────────────────────────────────────────────────

    def write_ground_truth(self, result: BootstrapResult, path: str | None = None) -> Path:
        """Write ground truth JSON compatible with --ground-truth.

        Format: {"column_name": "category_code", ...}
        """
        output_path = Path(path or self._config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.ground_truth, indent=2, sort_keys=True) + "\n"
        )
        return output_path
