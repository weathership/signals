"""Tests for the run report module."""

from __future__ import annotations

import json

from sigint.run_report import (
    AccuracyMetrics,
    ColumnResult,
    RunConfig,
    RunReport,
)


def _make_column_result(**overrides) -> ColumnResult:
    defaults = dict(
        source_table="personal_data",
        column_name="email",
        embedding_text="email | a@b.com",
        predicted_code="1.1.1.2.1",
        predicted_label="Email Address",
        confidence=0.85,
        boost=0.0,
        evidence="cosine=0.85 to Email Address",
        ground_truth_code="1.1.1.2.1",
        correct=True,
    )
    defaults.update(overrides)
    return ColumnResult(**defaults)


def _make_report(n_columns=3) -> RunReport:
    columns = [_make_column_result(column_name=f"col_{i}") for i in range(n_columns)]
    return RunReport(
        run_id="test123",
        timestamp="20260317T120000Z",
        config=RunConfig(
            taxonomy="annotations",
            classifier_method="cosine",
            embedding_model="all-MiniLM-L6-v2",
            confidence_threshold=0.25,
            name_match_boost=True,
            feature_set=["column_name", "sample_values"],
        ),
        columns=columns,
        accuracy=AccuracyMetrics(
            total_evaluated=3,
            correct=3,
            wrong=0,
            accuracy=1.0,
            boost_assisted=2,
            boost_dependent=0,
            misclassified=[],
        ),
        sage_results=[],
        label_distribution={"Email Address": 3},
    )


# ── JSON serialization ──────────────────────────────────────────────


class TestJsonSerialization:
    def test_write_and_read_json(self, tmp_path):
        report = _make_report()
        json_path = tmp_path / "report.json"
        report.write_json(json_path)

        assert json_path.exists()
        loaded = RunReport.from_json(json_path)
        assert loaded.run_id == "test123"
        assert loaded.config.taxonomy == "annotations"
        assert len(loaded.columns) == 3
        assert loaded.accuracy is not None
        assert loaded.accuracy.correct == 3

    def test_json_roundtrip_preserves_data(self, tmp_path):
        report = _make_report()
        json_path = tmp_path / "report.json"
        report.write_json(json_path)

        with open(json_path) as f:
            raw = json.load(f)

        assert raw["run_id"] == "test123"
        assert raw["config"]["embedding_model"] == "all-MiniLM-L6-v2"
        assert raw["accuracy"]["accuracy"] == 1.0
        assert raw["label_distribution"] == {"Email Address": 3}

    def test_creates_parent_dirs(self, tmp_path):
        report = _make_report()
        nested = tmp_path / "a" / "b" / "report.json"
        report.write_json(nested)
        assert nested.exists()

    def test_no_accuracy(self, tmp_path):
        report = RunReport(run_id="noacc", timestamp="t", columns=[])
        json_path = tmp_path / "report.json"
        report.write_json(json_path)
        loaded = RunReport.from_json(json_path)
        assert loaded.accuracy is None

    def test_sage_results_persisted(self, tmp_path):
        report = _make_report()
        report.sage_results = [{"feature": "column_name", "importance": 0.42}]
        json_path = tmp_path / "report.json"
        report.write_json(json_path)
        loaded = RunReport.from_json(json_path)
        assert loaded.sage_results[0]["feature"] == "column_name"


# ── Parquet serialization ────────────────────────────────────────────


class TestParquetSerialization:
    def test_write_parquet(self, tmp_path):
        report = _make_report()
        pq_path = tmp_path / "columns.parquet"
        report.write_parquet(pq_path)
        assert pq_path.exists()

        import pyarrow.parquet as pq

        table = pq.read_table(str(pq_path))
        assert table.num_rows == 3
        assert "predicted_code" in table.column_names
        assert "confidence" in table.column_names
        assert "correct" in table.column_names

    def test_empty_columns_no_file(self, tmp_path):
        report = RunReport(columns=[])
        pq_path = tmp_path / "columns.parquet"
        report.write_parquet(pq_path)
        assert not pq_path.exists()

    def test_parquet_creates_parent_dirs(self, tmp_path):
        report = _make_report(n_columns=1)
        nested = tmp_path / "x" / "y" / "columns.parquet"
        report.write_parquet(nested)
        assert nested.exists()


# ── AccuracyMetrics ──────────────────────────────────────────────────


class TestAccuracyMetrics:
    def test_misclassified_list(self):
        m = AccuracyMetrics(
            total_evaluated=10,
            correct=8,
            wrong=2,
            accuracy=0.8,
            boost_assisted=5,
            boost_dependent=1,
            misclassified=[
                {"column": "age", "expected": "AGE", "predicted": "DOB"},
            ],
        )
        assert len(m.misclassified) == 1
        assert m.misclassified[0]["column"] == "age"


# ── RunConfig ────────────────────────────────────────────────────────


class TestRunConfig:
    def test_feature_set(self):
        c = RunConfig(
            taxonomy="annotations",
            classifier_method="cosine",
            embedding_model="all-MiniLM-L6-v2",
            confidence_threshold=0.25,
            name_match_boost=True,
            feature_set=["column_name", "sample_values"],
        )
        assert "column_name" in c.feature_set
        assert len(c.feature_set) == 2


# ── ColumnResult ─────────────────────────────────────────────────────


class TestColumnResult:
    def test_no_ground_truth(self):
        cr = _make_column_result(ground_truth_code=None, correct=None)
        assert cr.correct is None

    def test_defaults(self):
        cr = ColumnResult(
            source_table="t",
            column_name="c",
            embedding_text="c",
            predicted_code="X",
            predicted_label="X",
            confidence=0.5,
            boost=0.0,
            evidence="test",
        )
        assert cr.ground_truth_code is None
        assert cr.correct is None
