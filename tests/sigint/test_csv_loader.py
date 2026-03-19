"""Tests for the csv_loader shared module."""

from __future__ import annotations

import csv
import textwrap
from pathlib import Path

import pytest

from sigint.csv_loader import build_feature_mask, group_by_table, load_csv_columns


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Create a minimal meta-tagging dataset directory."""
    # annotations.csv — should be skipped by load_csv_columns
    ann = tmp_path / "annotations.csv"
    ann.write_text(textwrap.dedent("""\
        ID,Ontology,Annotation,Definition,Deprecated
        1,Personal,PERS,Personal data,
        1.1,Name,NAME,Name data,
    """))

    # A data CSV with a few columns
    data = tmp_path / "users.csv"
    with open(data, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["users.email", "users.attr_1_1", "users.first_name", "users.row_id"])
        w.writerow(["alice@example.com", "1.1", "Alice", "1"])
        w.writerow(["bob@test.org", "1.1", "Bob", "2"])
        w.writerow(["carol@domain.co", "1.1", "Carol", "3"])

    # A second data CSV
    orders = tmp_path / "orders.csv"
    with open(orders, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["orders.order_id", "orders.amount"])
        w.writerow(["ORD-001", "99.99"])
        w.writerow(["ORD-002", "42.50"])

    return tmp_path


# ── load_csv_columns ─────────────────────────────────────────────────


class TestLoadCsvColumns:
    def test_loads_data_columns(self, data_dir: Path):
        records = load_csv_columns(data_dir)
        names = {r["column_name"] for r in records}
        assert "email" in names
        assert "first_name" in names

    def test_includes_annotation_columns(self, data_dir: Path):
        records = load_csv_columns(data_dir)
        names = {r["column_name"] for r in records}
        assert "attr_1_1" in names

    def test_includes_row_id(self, data_dir: Path):
        records = load_csv_columns(data_dir)
        names = {r["column_name"] for r in records}
        assert "row_id" in names

    def test_includes_all_columns(self, data_dir: Path):
        """All 4 users columns + 2 orders columns = 6 total."""
        records = load_csv_columns(data_dir)
        assert len(records) == 6

    def test_skips_annotations_csv(self, data_dir: Path):
        records = load_csv_columns(data_dir)
        tables = {r["source_table"] for r in records}
        assert "annotations" not in tables

    def test_collects_sample_values(self, data_dir: Path):
        records = load_csv_columns(data_dir)
        email_rec = next(r for r in records if r["column_name"] == "email")
        assert len(email_rec["sample_values"]) == 3
        assert "alice@example.com" in email_rec["sample_values"]

    def test_strips_table_prefix(self, data_dir: Path):
        records = load_csv_columns(data_dir)
        # "users.email" → "email"
        names = {r["column_name"] for r in records}
        assert "email" in names
        assert "users.email" not in names

    def test_preserves_headers(self, data_dir: Path):
        records = load_csv_columns(data_dir)
        email_rec = next(r for r in records if r["column_name"] == "email")
        assert "headers" in email_rec
        assert len(email_rec["headers"]) == 4

    def test_includes_multiple_tables(self, data_dir: Path):
        records = load_csv_columns(data_dir)
        tables = {r["source_table"] for r in records}
        assert "users" in tables
        assert "orders" in tables

    def test_empty_dir(self, tmp_path: Path):
        records = load_csv_columns(tmp_path)
        assert records == []

    def test_max_five_sample_values(self, tmp_path: Path):
        csv_path = tmp_path / "big.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["big.value"])
            for i in range(20):
                w.writerow([f"val_{i}"])

        records = load_csv_columns(tmp_path)
        assert len(records) == 1
        # Only first 5 non-empty values collected
        assert len(records[0]["sample_values"]) == 5


# ── build_feature_mask ───────────────────────────────────────────────


class TestBuildFeatureMask:
    def test_none_when_no_disabled(self):
        assert build_feature_mask(None) is None
        assert build_feature_mask([]) is None

    def test_disables_specified_features(self):
        mask = build_feature_mask(["sample_values", "sibling_context"])
        assert mask is not None
        assert mask["sample_values"] is False
        assert mask["sibling_context"] is False
        assert mask["column_name"] is True

    def test_all_features_present(self):
        from sigint.features import FEATURE_NAMES
        mask = build_feature_mask(["column_name"])
        assert mask is not None
        assert set(mask.keys()) == set(FEATURE_NAMES)

    def test_unknown_feature_warning(self, capsys):
        mask = build_feature_mask(["nonexistent_feature"])
        # Unknown features are ignored; all remain enabled
        assert mask is not None
        assert all(v is True for v in mask.values())
        captured = capsys.readouterr()
        assert "nonexistent_feature" in captured.err


# ── group_by_table ───────────────────────────────────────────────────


class TestGroupByTable:
    def test_groups_correctly(self):
        records = [
            {"source_table": "users", "column_name": "email"},
            {"source_table": "users", "column_name": "name"},
            {"source_table": "orders", "column_name": "amount"},
        ]
        grouped = group_by_table(records)
        assert len(grouped) == 2
        assert len(grouped["users"]) == 2
        assert len(grouped["orders"]) == 1

    def test_empty_records(self):
        assert group_by_table([]) == {}

    def test_single_table(self):
        records = [
            {"source_table": "t1", "column_name": "a"},
            {"source_table": "t1", "column_name": "b"},
        ]
        grouped = group_by_table(records)
        assert len(grouped) == 1
        assert len(grouped["t1"]) == 2
