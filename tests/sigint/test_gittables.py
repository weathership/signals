"""Tests for GitTables CTA benchmark support.

Covers:
- BFO-grounded taxonomy construction
- Parquet loading roundtrip
- Arrow type simplification
- Confusable pair validity
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


# ── Taxonomy tests ──────────────────────────────────────────────────


class TestGitTablesTaxonomy:
    """Tests for the BFO-grounded GitTables taxonomy."""

    @pytest.fixture()
    def category_set(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from config.sigint.gittables_taxonomy import gittables_category_set
        return gittables_category_set()

    def test_leaf_count(self, category_set):
        """Taxonomy has exactly 122 leaf categories matching dbpedia_labels.csv."""
        assert len(category_set.categories) == 122

    def test_all_leaves_have_parents(self, category_set):
        """Every leaf has a valid parent_code."""
        for cat in category_set.categories:
            assert cat.parent_code is not None, f"{cat.code} has no parent"
            assert cat.parent_code in category_set.all_by_code, (
                f"{cat.code} parent {cat.parent_code} not in taxonomy"
            )

    def test_internal_nodes_exist(self, category_set):
        """Taxonomy has internal (parent) nodes."""
        internal_count = len(category_set.all_categories) - len(category_set.categories)
        assert internal_count >= 15, f"Expected >=15 internal nodes, got {internal_count}"

    def test_root_exists(self, category_set):
        """Taxonomy has a root node with no parent."""
        roots = [c for c in category_set.all_categories if c.parent_code is None]
        assert len(roots) == 1
        assert roots[0].code == "entity"

    def test_bfo_anchors(self, category_set):
        """Key BFO-aligned internal nodes exist."""
        expected = [
            "continuant",
            "occurrent",
            "continuant.gdc",
            "continuant.quality",
            "continuant.ic",
            "occurrent.process",
            "occurrent.temporal",
        ]
        for code in expected:
            assert code in category_set.all_by_code, f"Missing BFO anchor: {code}"

    def test_descendants(self, category_set):
        """descendants() returns correct leaf sets."""
        temporal_leaves = category_set.descendants("occurrent.temporal")
        expected_temporal = {"date", "start date", "end date", "year", "time",
                            "second", "duration", "period", "start"}
        assert temporal_leaves == expected_temporal

    def test_ancestors(self, category_set):
        """ancestors() returns correct path to root."""
        ancestors = category_set.ancestors("name")
        assert "continuant.gdc.identifier.name" in ancestors
        assert "continuant.gdc.identifier" in ancestors
        assert "continuant.gdc" in ancestors
        assert "continuant" in ancestors
        assert "entity" in ancestors

    def test_leaf_codes_are_dbpedia_labels(self, category_set):
        """Leaf codes are DBpedia property labels (lowercase alpha)."""
        for cat in category_set.categories:
            assert cat.code == cat.label, (
                f"Leaf code {cat.code} != label {cat.label}"
            )

    def test_taxonomy_name(self, category_set):
        """Taxonomy is named 'gittables'."""
        assert category_set.name == "gittables"

    def test_embedding_text_not_empty(self, category_set):
        """All categories have non-empty embedding text."""
        for cat in category_set.all_categories:
            assert cat.embedding_text, f"{cat.code} has empty embedding_text"

    def test_known_leaf_types(self, category_set):
        """Spot-check known DBpedia types are present."""
        known = ["name", "date", "country", "company", "height", "description",
                 "author", "gender", "city", "event"]
        for code in known:
            assert code in category_set.by_code, f"Missing leaf: {code}"


class TestConfusablePairs:
    """Tests for GitTables confusable pairs."""

    @pytest.fixture()
    def category_set(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from config.sigint.gittables_taxonomy import gittables_category_set
        return gittables_category_set()

    @pytest.fixture()
    def pairs(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from config.sigint.gittables_taxonomy import GITTABLES_CONFUSABLE_PAIRS
        return GITTABLES_CONFUSABLE_PAIRS

    def test_pairs_not_empty(self, pairs):
        """At least some confusable pairs are defined."""
        assert len(pairs) >= 10

    def test_all_codes_exist(self, category_set, pairs):
        """Both codes in every confusable pair exist in the taxonomy."""
        for a, b in pairs:
            assert a in category_set.by_code, f"Confusable pair code {a} not in taxonomy"
            assert b in category_set.by_code, f"Confusable pair code {b} not in taxonomy"

    def test_pairs_are_distinct(self, pairs):
        """No pair has the same code on both sides."""
        for a, b in pairs:
            assert a != b, f"Self-pair: ({a}, {b})"

    def test_get_confusable_pairs_registry(self):
        """Registry returns GitTables pairs."""
        from sigint.confusable_pairs import get_confusable_pairs
        pairs = get_confusable_pairs("gittables")
        assert len(pairs) >= 10


# ── Parquet loader tests ────────────────────────────────────────────


class TestLoadParquetColumns:
    """Tests for load_parquet_columns() roundtrip."""

    def _write_test_parquet(self, path: Path, records: list[dict]) -> None:
        """Write a test parquet file in the expected schema."""
        schema = pa.schema([
            ("source_table", pa.string()),
            ("column_name", pa.string()),
            ("column_type", pa.string()),
            ("sample_values", pa.string()),
            ("sibling_columns", pa.string()),
        ])
        arrays = {
            "source_table": pa.array([r["source_table"] for r in records]),
            "column_name": pa.array([r["column_name"] for r in records]),
            "column_type": pa.array([r["column_type"] for r in records]),
            "sample_values": pa.array([r["sample_values"] for r in records]),
            "sibling_columns": pa.array([r["sibling_columns"] for r in records]),
        }
        table = pa.table(arrays, schema=schema)
        pq.write_table(table, str(path))

    def test_roundtrip(self):
        """Records survive write→read roundtrip."""
        from sigint.csv_loader import load_parquet_columns

        records = [
            {
                "source_table": "test_table",
                "column_name": "name",
                "column_type": "STRING",
                "sample_values": json.dumps(["Alice", "Bob", "Charlie"]),
                "sibling_columns": json.dumps(["age", "city"]),
            },
            {
                "source_table": "test_table",
                "column_name": "age",
                "column_type": "INT",
                "sample_values": json.dumps(["25", "30", "35"]),
                "sibling_columns": json.dumps(["name", "city"]),
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.parquet"
            self._write_test_parquet(path, records)
            loaded = load_parquet_columns(path)

        assert len(loaded) == 2
        assert loaded[0]["source_table"] == "test_table"
        assert loaded[0]["column_name"] == "name"
        assert loaded[0]["column_type"] == "STRING"
        assert loaded[0]["sample_values"] == ["Alice", "Bob", "Charlie"]
        assert "age" in loaded[0]["headers"]

    def test_empty_sample_values(self):
        """Empty sample values are handled."""
        from sigint.csv_loader import load_parquet_columns

        records = [{
            "source_table": "t1",
            "column_name": "empty_col",
            "column_type": "STRING",
            "sample_values": json.dumps([]),
            "sibling_columns": json.dumps([]),
        }]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.parquet"
            self._write_test_parquet(path, records)
            loaded = load_parquet_columns(path)

        assert loaded[0]["sample_values"] == []

    def test_values_coerced_to_strings(self):
        """Numeric values in JSON are stringified."""
        from sigint.csv_loader import load_parquet_columns

        records = [{
            "source_table": "t1",
            "column_name": "price",
            "column_type": "FLOAT",
            "sample_values": json.dumps([19.99, 29.99, 39.99]),
            "sibling_columns": json.dumps(["name"]),
        }]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.parquet"
            self._write_test_parquet(path, records)
            loaded = load_parquet_columns(path)

        assert all(isinstance(v, str) for v in loaded[0]["sample_values"])
        assert loaded[0]["sample_values"][0] == "19.99"


# ── Arrow type mapping tests ────────────────────────────────────────


class TestArrowTypeMapping:
    """Tests for simplify_arrow_type()."""

    @pytest.fixture()
    def simplify(self):
        from scripts.download_gittables_benchmark import simplify_arrow_type
        return simplify_arrow_type

    def test_int_types(self, simplify):
        assert simplify(pa.int64()) == "INT"
        assert simplify(pa.int32()) == "INT"
        assert simplify(pa.uint8()) == "INT"

    def test_float_types(self, simplify):
        assert simplify(pa.float64()) == "FLOAT"
        assert simplify(pa.float32()) == "FLOAT"

    def test_string_types(self, simplify):
        assert simplify(pa.utf8()) == "STRING"
        assert simplify(pa.large_utf8()) == "STRING"

    def test_bool_type(self, simplify):
        assert simplify(pa.bool_()) == "BOOL"

    def test_timestamp_types(self, simplify):
        assert simplify(pa.timestamp("ns")) == "TIMESTAMP"
        assert simplify(pa.date32()) == "TIMESTAMP"

    def test_unknown_defaults_to_string(self, simplify):
        assert simplify(pa.binary()) == "STRING"


# ── Leaf label list test ────────────────────────────────────────────


class TestLeafLabels:
    """Tests for get_leaf_labels()."""

    def test_returns_122_labels(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from config.sigint.gittables_taxonomy import get_leaf_labels
        labels = get_leaf_labels()
        assert len(labels) == 122

    def test_labels_are_unique(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from config.sigint.gittables_taxonomy import get_leaf_labels
        labels = get_leaf_labels()
        assert len(labels) == len(set(labels))


# ── Pattern category map tests ────────────────────────────────────


class TestPatternCategoryMap:
    """Tests for GITTABLES_PATTERN_MAP and registry integration."""

    @pytest.fixture()
    def pattern_map(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from config.sigint.gittables_taxonomy import GITTABLES_PATTERN_MAP
        return GITTABLES_PATTERN_MAP

    @pytest.fixture()
    def category_set(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from config.sigint.gittables_taxonomy import gittables_category_set
        return gittables_category_set()

    def test_map_not_empty(self, pattern_map):
        assert len(pattern_map) >= 5

    def test_all_codes_are_valid_leaves(self, pattern_map, category_set):
        """Every target code in the pattern map must be a leaf category."""
        for pattern, code in pattern_map.items():
            assert code in category_set.by_code, (
                f"Pattern {pattern} maps to {code} which is not a leaf category"
            )

    def test_date_maps_to_date(self, pattern_map):
        assert pattern_map["date_iso_pattern"] == "date"

    def test_email_maps_to_address(self, pattern_map):
        assert pattern_map["email_pattern"] == "address"

    def test_uuid_maps_to_id(self, pattern_map):
        assert pattern_map["uuid_pattern"] == "id"

    def test_registry_returns_gittables_map(self):
        """get_pattern_category_map('gittables') returns GITTABLES_PATTERN_MAP."""
        from sigint.mass_functions import get_pattern_category_map
        m = get_pattern_category_map("gittables")
        assert m["date_iso_pattern"] == "date"
        assert m["uuid_pattern"] == "id"

    def test_registry_returns_sigdg_for_unknown(self):
        """Unknown taxonomy falls back to SIGDG map."""
        from sigint.mass_functions import get_pattern_category_map
        m = get_pattern_category_map("unknown_taxonomy")
        assert m["email_pattern"] == "0076"


# ── Enriched embedding text tests ────────────────────────────────


class TestEnrichedEmbeddingText:
    """Spot-check that embedding_text includes value-pattern descriptions."""

    @pytest.fixture()
    def category_set(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from config.sigint.gittables_taxonomy import gittables_category_set
        return gittables_category_set()

    def test_date_has_yyyy_mm_dd(self, category_set):
        cat = category_set.by_code["date"]
        assert "YYYY-MM-DD" in cat.embedding_text

    def test_id_has_sequential(self, category_set):
        cat = category_set.by_code["id"]
        assert "sequential" in cat.embedding_text.lower()

    def test_country_has_country_names(self, category_set):
        cat = category_set.by_code["country"]
        assert "United States" in cat.embedding_text or "country names" in cat.embedding_text

    def test_description_has_long(self, category_set):
        cat = category_set.by_code["description"]
        assert "long" in cat.embedding_text.lower() or "paragraph" in cat.embedding_text.lower()

    def test_gender_has_low_cardinality(self, category_set):
        cat = category_set.by_code["gender"]
        assert "low cardinality" in cat.embedding_text.lower() or "Male" in cat.embedding_text

    def test_type_has_categorical(self, category_set):
        cat = category_set.by_code["type"]
        assert "categorical" in cat.embedding_text.lower()

    def test_height_has_decimal(self, category_set):
        cat = category_set.by_code["height"]
        assert "decimal" in cat.embedding_text.lower() or "1.75" in cat.embedding_text
