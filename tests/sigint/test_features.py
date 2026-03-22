"""Tests for the feature extraction module."""

from __future__ import annotations

from sigint.features import (
    FEATURE_NAMES,
    ColumnFeatures,
    detect_patterns,
    extract_features,
    _is_generic_name,
    _generate_value_description,
    _numeric_ratio,
    _shannon_entropy,
)
from sigint.sampler import ColumnSample


def _sample(name="ssn", col_type="STRING", values=None, null_count=0, total_count=100):
    return ColumnSample(
        column_name=name,
        column_type=col_type,
        values=values or [],
        null_count=null_count,
        total_count=total_count,
    )


# ── Pattern detection ────────────────────────────────────────────────


class TestPatternDetection:
    def test_email_pattern(self):
        vals = ["alice@example.com", "bob@test.org", "carol@domain.co.uk"]
        pats = detect_patterns(vals)
        assert "email_pattern" in pats

    def test_ssn_pattern(self):
        vals = ["123-45-6789", "987-65-4321", "111-22-3333"]
        pats = detect_patterns(vals)
        assert "ssn_pattern" in pats

    def test_ipv4_pattern(self):
        vals = ["192.168.1.1", "10.0.0.1", "172.16.0.1"]
        pats = detect_patterns(vals)
        assert "ipv4_pattern" in pats

    def test_uuid_pattern(self):
        vals = [
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        ]
        pats = detect_patterns(vals)
        assert "uuid_pattern" in pats

    def test_date_iso_pattern(self):
        vals = ["2024-01-15", "2023-12-31", "2025-06-01"]
        pats = detect_patterns(vals)
        assert "date_iso_pattern" in pats

    def test_url_pattern(self):
        vals = ["https://example.com", "http://test.org/path"]
        pats = detect_patterns(vals)
        assert "url_pattern" in pats

    def test_credit_card_pattern(self):
        vals = ["4111111111111111", "5500000000000004", "378282246310005"]
        pats = detect_patterns(vals)
        assert "credit_card_pattern" in pats

    def test_phone_pattern(self):
        vals = ["+1-555-123-4567", "(555) 123-4567", "555.123.4567"]
        pats = detect_patterns(vals)
        assert "phone_pattern" in pats

    def test_no_pattern_for_random_text(self):
        vals = ["hello world", "foo bar baz", "test data"]
        pats = detect_patterns(vals)
        assert pats == []

    def test_empty_values(self):
        assert detect_patterns([]) == []

    def test_patterns_sorted(self):
        vals = ["123-45-6789"]
        pats = detect_patterns(vals)
        assert pats == sorted(pats)


# ── Utility functions ────────────────────────────────────────────────


class TestUtilities:
    def test_shannon_entropy_uniform(self):
        # 4 distinct lengths → max entropy for 4 classes is 2.0 bits
        vals = ["a", "bb", "ccc", "dddd"]
        e = _shannon_entropy(vals)
        assert abs(e - 2.0) < 0.01

    def test_shannon_entropy_zero(self):
        # All same length → zero entropy
        vals = ["aa", "bb", "cc"]
        e = _shannon_entropy(vals)
        assert e == 0.0

    def test_shannon_entropy_empty(self):
        assert _shannon_entropy([]) == 0.0

    def test_numeric_ratio_all_numeric(self):
        vals = ["1", "2.5", "3,000", "-4.2"]
        assert _numeric_ratio(vals) == 1.0

    def test_numeric_ratio_none_numeric(self):
        vals = ["hello", "world"]
        assert _numeric_ratio(vals) == 0.0

    def test_numeric_ratio_mixed(self):
        vals = ["42", "hello", "3.14", "world"]
        assert _numeric_ratio(vals) == 0.5

    def test_numeric_ratio_empty(self):
        assert _numeric_ratio([]) == 0.0


# ── extract_features ─────────────────────────────────────────────────


class TestExtractFeatures:
    def test_basic_extraction(self):
        s = _sample("payment_card_number", "STRING", ["4111111111111111", "5500000000000004"])
        f = extract_features(s, source_table="personal_data")
        assert f.column_name_humanized == "payment card number"
        assert f.column_type is None  # STRING suppressed
        assert f.sample_values_text is not None
        assert f.cardinality == 2
        assert f.source_table == "personal_data"
        assert "credit_card_pattern" in f.pattern_signals

    def test_non_string_type_preserved(self):
        s = _sample("age", "INT", ["25", "30"])
        f = extract_features(s)
        assert f.column_type == "int"

    def test_null_ratio(self):
        s = _sample("col", "STRING", ["a"], null_count=30, total_count=100)
        f = extract_features(s)
        assert f.null_ratio == 0.3

    def test_null_ratio_zero_total(self):
        s = _sample("col", "STRING", ["a"], null_count=0, total_count=0)
        f = extract_features(s)
        assert f.null_ratio is None

    def test_avg_value_length(self):
        s = _sample("col", "STRING", ["ab", "abcd"])
        f = extract_features(s)
        assert f.avg_value_length == 3.0

    def test_siblings(self):
        main = _sample("email", "STRING", ["a@b.com"])
        sib1 = _sample("first_name", "STRING", ["Alice"])
        sib2 = _sample("last_name", "STRING", ["Smith"])
        f = extract_features(main, siblings=[main, sib1, sib2])
        assert "first name" in f.sibling_names
        assert "last name" in f.sibling_names
        assert "email" not in f.sibling_names  # self excluded

    def test_no_values(self):
        s = _sample("col", "STRING", [])
        f = extract_features(s)
        assert f.sample_values_text is None
        assert f.cardinality is None
        assert f.value_entropy is None
        assert f.avg_value_length is None
        assert f.numeric_ratio is None

    def test_frozen(self):
        s = _sample("col", "STRING", ["a"])
        f = extract_features(s)
        try:
            f.column_name_humanized = "nope"  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass


# ── ColumnFeatures.to_embedding_text ─────────────────────────────────


class TestToEmbeddingText:
    def test_all_features_enabled(self):
        f = ColumnFeatures(
            column_name_humanized="payment card number",
            column_type="bigint",
            sample_values_text="4111111111111111, 5500000000000004",
            cardinality=2,
            null_ratio=0.05,
            value_entropy=1.0,
            pattern_signals=["credit_card_pattern"],
            avg_value_length=16.0,
            numeric_ratio=1.0,
            sibling_names=["first name", "last name"],
            source_table="personal_data",
        )
        text = f.to_embedding_text()
        assert "payment card number" in text
        assert "bigint" in text
        assert "4111111111111111" in text
        assert "cardinality=2" in text
        assert "null_ratio=0.05" in text
        assert "entropy=1.00" in text
        assert "credit_card_pattern" in text
        assert "avg_len=16.0" in text
        assert "numeric=1.00" in text
        assert "siblings: first name, last name" in text
        assert "table=personal_data" in text

    def test_mask_disables_features(self):
        f = ColumnFeatures(
            column_name_humanized="email",
            column_type=None,
            sample_values_text="a@b.com",
            cardinality=1,
            null_ratio=None,
            value_entropy=0.0,
            pattern_signals=["email_pattern"],
            avg_value_length=7.0,
            numeric_ratio=0.0,
            sibling_names=["name"],
            source_table="users",
        )
        mask = {n: False for n in FEATURE_NAMES}
        mask["column_name"] = True
        text = f.to_embedding_text(mask)
        assert text == "email"

    def test_mask_none_means_all(self):
        f = ColumnFeatures(
            column_name_humanized="col",
            column_type="int",
            sample_values_text="1",
            cardinality=1,
            null_ratio=None,
            value_entropy=0.0,
        )
        text_all = f.to_embedding_text(None)
        text_default = f.to_embedding_text()
        assert text_all == text_default

    def test_empty_features_gives_empty_string(self):
        f = ColumnFeatures(
            column_name_humanized="",
            column_type=None,
            sample_values_text=None,
            cardinality=None,
            null_ratio=None,
            value_entropy=None,
        )
        assert f.to_embedding_text() == ""

    def test_zero_null_ratio_suppressed(self):
        f = ColumnFeatures(
            column_name_humanized="col",
            column_type=None,
            sample_values_text=None,
            cardinality=None,
            null_ratio=0.0,
            value_entropy=None,
        )
        text = f.to_embedding_text()
        assert "null_ratio" not in text

    def test_zero_entropy_suppressed(self):
        f = ColumnFeatures(
            column_name_humanized="col",
            column_type=None,
            sample_values_text=None,
            cardinality=None,
            null_ratio=None,
            value_entropy=0.0,
        )
        text = f.to_embedding_text()
        assert "entropy" not in text

    def test_zero_numeric_ratio_suppressed(self):
        f = ColumnFeatures(
            column_name_humanized="col",
            column_type=None,
            sample_values_text=None,
            cardinality=None,
            null_ratio=None,
            value_entropy=None,
            numeric_ratio=0.0,
        )
        text = f.to_embedding_text()
        assert "numeric" not in text


class TestFeatureValue:
    def test_feature_value_isolation(self):
        f = ColumnFeatures(
            column_name_humanized="email",
            column_type="varchar",
            sample_values_text="a@b.com",
            cardinality=1,
            null_ratio=None,
            value_entropy=0.0,
            source_table="users",
        )
        # Only column_name should appear
        v = f.feature_value("column_name")
        assert "email" in v
        assert "varchar" not in v
        assert "users" not in v

    def test_feature_names_property(self):
        f = ColumnFeatures(
            column_name_humanized="x",
            column_type=None,
            sample_values_text=None,
            cardinality=None,
            null_ratio=None,
            value_entropy=None,
        )
        assert f.feature_names == FEATURE_NAMES
        assert len(f.feature_names) == 12


# ── Generic name detection ────────────────────────────────────────


class TestGenericNameDetection:
    def test_col_with_digit(self):
        assert _is_generic_name("col0") is True
        assert _is_generic_name("col1") is True
        assert _is_generic_name("col123") is True

    def test_bare_col(self):
        assert _is_generic_name("col") is True

    def test_column_with_digit(self):
        assert _is_generic_name("column0") is True
        assert _is_generic_name("column12") is True

    def test_field_var(self):
        assert _is_generic_name("field0") is True
        assert _is_generic_name("var1") is True

    def test_unnamed(self):
        assert _is_generic_name("Unnamed") is True
        assert _is_generic_name("Unnamed: 0") is True

    def test_empty_string(self):
        assert _is_generic_name("") is True

    def test_underscore(self):
        assert _is_generic_name("_") is True

    def test_digit_only(self):
        assert _is_generic_name("0") is True
        assert _is_generic_name("42") is True

    def test_real_names_not_generic(self):
        assert _is_generic_name("email") is False
        assert _is_generic_name("customer_name") is False
        assert _is_generic_name("date_of_birth") is False
        assert _is_generic_name("price") is False


# ── Value description ─────────────────────────────────────────────


class TestValueDescription:
    def test_date_pattern(self):
        desc = _generate_value_description(
            ["2024-01-15", "2023-12-31"], None, ["date_iso_pattern"]
        )
        assert "date" in desc.lower()
        assert "YYYY-MM-DD" in desc

    def test_email_pattern(self):
        desc = _generate_value_description(
            ["a@b.com", "c@d.org"], None, ["email_pattern"]
        )
        assert "email" in desc.lower()

    def test_url_pattern(self):
        desc = _generate_value_description(
            ["https://example.com"], None, ["url_pattern"]
        )
        assert "URL" in desc

    def test_uuid_pattern(self):
        desc = _generate_value_description(
            ["550e8400-e29b-41d4-a716-446655440000"], None, ["uuid_pattern"]
        )
        assert "UUID" in desc

    def test_sequential_integers(self):
        desc = _generate_value_description(
            ["1", "2", "3", "4", "5"], "int", []
        )
        assert "sequential" in desc.lower()

    def test_decimal_numbers(self):
        desc = _generate_value_description(
            ["1.5", "2.7", "3.14"], None, []
        )
        assert "decimal" in desc.lower()

    def test_long_text(self):
        long_val = "x" * 120
        desc = _generate_value_description([long_val], None, [])
        assert "long text" in desc.lower()

    def test_categorical_labels(self):
        desc = _generate_value_description(
            ["A", "B", "A", "B", "A", "B"], None, []
        )
        assert "categorical" in desc.lower()

    def test_empty_values(self):
        assert _generate_value_description([], None, []) == ""

    def test_short_text(self):
        desc = _generate_value_description(
            ["hello", "world", "foo", "bar", "baz"], None, []
        )
        assert "text" in desc.lower()


# ── Generic name substitution in embedding text ──────────────────


class TestGenericNameSubstitution:
    def test_generic_name_replaced_by_value_description(self):
        f = ColumnFeatures(
            column_name_humanized="col0",
            column_type=None,
            sample_values_text="2024-01-15, 2023-12-31",
            cardinality=2,
            null_ratio=None,
            value_entropy=0.0,
            value_description="column of date values in YYYY-MM-DD format",
            is_generic_name=True,
        )
        text = f.to_embedding_text()
        assert "col0" not in text
        assert "date values" in text

    def test_real_name_gets_value_description_appended(self):
        f = ColumnFeatures(
            column_name_humanized="price",
            column_type="float",
            sample_values_text="19.99, 29.99",
            cardinality=2,
            null_ratio=None,
            value_entropy=0.0,
            value_description="column of decimal numeric measurements",
            is_generic_name=False,
        )
        text = f.to_embedding_text()
        assert "price" in text
        assert "decimal numeric" in text

    def test_generic_name_ablation_removes_description(self):
        f = ColumnFeatures(
            column_name_humanized="col0",
            column_type=None,
            sample_values_text="a@b.com",
            cardinality=1,
            null_ratio=None,
            value_entropy=0.0,
            value_description="column of email addresses",
            is_generic_name=True,
        )
        mask = {n: True for n in FEATURE_NAMES}
        mask["column_name"] = False
        text = f.to_embedding_text(mask)
        assert "email" not in text
        assert "col0" not in text

    def test_extract_features_sets_generic_flag(self):
        s = _sample("col0", "INT", ["1", "2", "3", "4", "5"])
        f = extract_features(s)
        assert f.is_generic_name is True
        assert f.value_description != ""

    def test_extract_features_real_name_not_generic(self):
        s = _sample("customer_email", "STRING", ["a@b.com", "c@d.org"])
        f = extract_features(s)
        assert f.is_generic_name is False
