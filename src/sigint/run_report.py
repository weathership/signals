"""Structured run reports for classification pipeline experiments.

Captures per-column results, accuracy metrics, SAGE analysis, and
configuration for reproducibility and comparison across runs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass
class ColumnResult:
    """Classification result for a single column."""

    source_table: str
    column_name: str
    embedding_text: str
    predicted_code: str
    predicted_label: str
    confidence: float
    boost: float
    evidence: str
    ground_truth_code: str | None = None
    correct: bool | None = None
    # Optional DST fields (populated when --dst is used)
    dst_belief: float = 0.0
    dst_plausibility: float = 0.0
    dst_uncertainty_gap: float = 0.0
    dst_conflict: float = 0.0
    dst_needs_clarification: bool = False
    dst_evidence_sources: str = ""
    dst_belief_path: str = ""


@dataclass
class AccuracyMetrics:
    """Aggregate accuracy metrics for a pipeline run."""

    total_evaluated: int
    correct: int
    wrong: int
    accuracy: float
    boost_assisted: int
    boost_dependent: int
    misclassified: list[dict] = field(default_factory=list)


@dataclass
class RunConfig:
    """Configuration snapshot for a pipeline run."""

    taxonomy: str
    classifier_method: str
    embedding_model: str
    confidence_threshold: float
    name_match_boost: bool
    feature_set: list[str] = field(default_factory=list)


@dataclass
class RunReport:
    """Complete report for a classification pipeline run."""

    run_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    config: RunConfig = field(default_factory=lambda: RunConfig(
        taxonomy="", classifier_method="", embedding_model="",
        confidence_threshold=0.0, name_match_boost=True,
    ))
    columns: list[ColumnResult] = field(default_factory=list)
    accuracy: AccuracyMetrics | None = None
    sage_results: list[dict] = field(default_factory=list)
    label_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize the full report to a JSON-compatible dict."""
        d = asdict(self)
        return d

    def write_json(self, path: Path) -> None:
        """Write report to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def write_parquet(self, path: Path) -> None:
        """Write per-column results to a parquet file."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        if not self.columns:
            return

        arrays = {
            "source_table": pa.array([c.source_table for c in self.columns]),
            "column_name": pa.array([c.column_name for c in self.columns]),
            "embedding_text": pa.array([c.embedding_text for c in self.columns]),
            "predicted_code": pa.array([c.predicted_code for c in self.columns]),
            "predicted_label": pa.array([c.predicted_label for c in self.columns]),
            "confidence": pa.array(
                [c.confidence for c in self.columns], type=pa.float64()
            ),
            "boost": pa.array([c.boost for c in self.columns], type=pa.float64()),
            "evidence": pa.array([c.evidence for c in self.columns]),
            "ground_truth_code": pa.array(
                [c.ground_truth_code or "" for c in self.columns]
            ),
            "correct": pa.array(
                [c.correct if c.correct is not None else False for c in self.columns]
            ),
        }

        table = pa.table(arrays)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, str(path))

    @classmethod
    def from_json(cls, path: Path) -> RunReport:
        """Load a RunReport from a JSON file."""
        with open(path) as f:
            d = json.load(f)

        config = RunConfig(**d.get("config", {}))
        columns = [ColumnResult(**c) for c in d.get("columns", [])]
        accuracy = (
            AccuracyMetrics(**d["accuracy"]) if d.get("accuracy") else None
        )

        return cls(
            run_id=d.get("run_id", ""),
            timestamp=d.get("timestamp", ""),
            config=config,
            columns=columns,
            accuracy=accuracy,
            sage_results=d.get("sage_results", []),
            label_distribution=d.get("label_distribution", {}),
        )
