"""Tests for schema discovery — naming patterns, FK hints, co-occurrence."""

from __future__ import annotations

from sigint.schema_discovery import (
    discover_elements,
    discover_fk_hints,
    refine_elements,
    _normalise,
    _infer_role,
)
from sigint.data_element import DataElementCatalog


# ── Normalisation helpers ────────────────────────────────────────


class TestNormalise:
    def test_snake_case(self):
        assert _normalise("card_number") == "card_number"

    def test_camel_case(self):
        assert _normalise("cardNumber") == "card_number"

    def test_hyphen(self):
        assert _normalise("card-number") == "card_number"

    def test_mixed(self):
        assert _normalise("PaymentCardNumber") == "payment_card_number"


class TestInferRole:
    def test_identifier(self):
        assert _infer_role("sample_id") == "identifier"
        assert _infer_role("id") == "identifier"

    def test_temporal(self):
        assert _infer_role("collection_date") == "temporal"
        assert _infer_role("created_timestamp") == "temporal"

    def test_attribute(self):
        assert _infer_role("card_number") == "attribute"
        assert _infer_role("first_name") == "attribute"


# ── Pattern-based discovery ──────────────────────────────────────


class TestDiscoverElements:
    def test_payment_card_pattern(self):
        tables = {
            "transactions": [
                {"column_name": "card_number"},
                {"column_name": "cvv"},
                {"column_name": "expiry_date"},
                {"column_name": "amount"},
            ]
        }
        catalog = discover_elements(tables)
        names = [e.name for e in catalog.elements]
        assert "PaymentCard" in names
        de = next(e for e in catalog.elements if e.name == "PaymentCard")
        assert de.domain == "finance"
        assert "card_number" in de.column_names
        assert "cvv" in de.column_names

    def test_postal_address_pattern(self):
        tables = {
            "customers": [
                {"column_name": "street"},
                {"column_name": "city"},
                {"column_name": "state"},
                {"column_name": "zip_code"},
                {"column_name": "customer_id"},
            ]
        }
        catalog = discover_elements(tables)
        names = [e.name for e in catalog.elements]
        assert "PostalAddress" in names

    def test_person_name_pattern(self):
        tables = {
            "employees": [
                {"column_name": "first_name"},
                {"column_name": "last_name"},
                {"column_name": "email"},
                {"column_name": "department"},
            ]
        }
        catalog = discover_elements(tables)
        names = [e.name for e in catalog.elements]
        assert "PersonName" in names

    def test_biospecimen_collection_pattern(self):
        """LIMS use case: tissue biopsy with sample/instrument attributes."""
        tables = {
            "samples": [
                {"column_name": "sample_id"},
                {"column_name": "sample_location"},
                {"column_name": "specimen_type"},
                {"column_name": "collection_date"},
                {"column_name": "anatomical_site"},
            ]
        }
        catalog = discover_elements(tables)
        names = [e.name for e in catalog.elements]
        assert "BiospecimenCollection" in names
        de = next(e for e in catalog.elements if e.name == "BiospecimenCollection")
        assert de.domain == "healthcare"
        assert len(de.members) >= 3

    def test_no_match_below_threshold(self):
        """Single indicator match shouldn't trigger a data element."""
        tables = {
            "misc": [
                {"column_name": "street"},
                {"column_name": "unrelated_col"},
            ]
        }
        catalog = discover_elements(tables)
        # PostalAddress requires min_match=2, "street" alone is only 1
        names = [e.name for e in catalog.elements]
        assert "PostalAddress" not in names

    def test_multiple_patterns_same_table(self):
        tables = {
            "customer_payments": [
                {"column_name": "card_number"},
                {"column_name": "cvv"},
                {"column_name": "first_name"},
                {"column_name": "last_name"},
                {"column_name": "street"},
                {"column_name": "city"},
                {"column_name": "zip_code"},
            ]
        }
        catalog = discover_elements(tables)
        names = [e.name for e in catalog.elements]
        assert "PaymentCard" in names
        assert "PersonName" in names
        assert "PostalAddress" in names

    def test_camel_case_column_names(self):
        tables = {
            "payments": [
                {"column_name": "cardNumber"},
                {"column_name": "cardVerificationValue"},
                {"column_name": "expiryDate"},
            ]
        }
        catalog = discover_elements(tables)
        names = [e.name for e in catalog.elements]
        # cardNumber normalises to card_number → matches "card_number"
        # expiryDate normalises to expiry_date → matches "expiry"
        assert "PaymentCard" in names

    def test_cross_table_merge(self):
        """Same DE discovered in two tables merges into one element."""
        tables = {
            "billing": [
                {"column_name": "card_number"},
                {"column_name": "cvv"},
            ],
            "refunds": [
                {"column_name": "pan"},
                {"column_name": "expiry"},
            ],
        }
        catalog = discover_elements(tables)
        payment_des = [e for e in catalog.elements if e.name == "PaymentCard"]
        assert len(payment_des) == 1  # merged
        assert payment_des[0].tables == {"billing", "refunds"}

    def test_empty_tables(self):
        catalog = discover_elements({})
        assert catalog.elements == []


# ── FK hint detection ────────────────────────────────────────────


class TestDiscoverFKHints:
    def test_simple_fk(self):
        tables = {
            "samples": ["sample_id", "instrument_id", "specimen_type"],
            "instruments": ["instrument_id", "name", "model"],
        }
        hints = discover_fk_hints(tables)
        assert len(hints) >= 1
        assert ("samples", "instrument_id", "instruments") in hints

    def test_plural_table_match(self):
        tables = {
            "orders": ["order_id", "customer_id", "total"],
            "customers": ["customer_id", "name", "email"],
        }
        hints = discover_fk_hints(tables)
        assert ("orders", "customer_id", "customers") in hints

    def test_no_self_reference(self):
        tables = {
            "samples": ["sample_id", "parent_sample_id"],
        }
        hints = discover_fk_hints(tables)
        # sample_id points to "sample" which matches "samples" → should be filtered
        # parent_sample_id → "parent_sample" → no match
        self_refs = [(s, c, t) for s, c, t in hints if s == t]
        assert len(self_refs) == 0

    def test_no_match(self):
        tables = {
            "data": ["col_a", "col_b"],
        }
        hints = discover_fk_hints(tables)
        assert hints == []


# ── Post-classification refinement ───────────────────────────────


class TestRefineElements:
    def test_category_co_occurrence(self):
        """PaymentCard affinity: {0070, 0073, 0075}."""
        initial = DataElementCatalog(elements=[])
        gt = {
            "pan": "0070",         # PaymentCardData
            "cardholder": "0073",  # FullName
            "billing_addr": "0075",  # PostalAddress
            "amount": "0050",
        }
        tables = {
            "transactions": [
                {"column_name": "pan"},
                {"column_name": "cardholder"},
                {"column_name": "billing_addr"},
                {"column_name": "amount"},
            ]
        }
        refined = refine_elements(initial, gt, tables)
        names = [e.name for e in refined.elements]
        assert "PaymentCard" in names
        de = next(e for e in refined.elements if e.name == "PaymentCard")
        assert de.source == "co-occurrence"
        # Only columns with matching affinity codes
        assert "pan" in de.column_names
        assert "cardholder" in de.column_names
        assert "amount" not in de.column_names

    def test_no_duplicate_discovery(self):
        """If PaymentCard already discovered, co-occurrence shouldn't add another."""
        from sigint.data_element import DataElement, DataElementMember
        existing = DataElementCatalog(elements=[
            DataElement("PaymentCard", "finance", "test", [
                DataElementMember("card_number", "t1"),
            ]),
        ])
        gt = {"pan": "0070", "name": "0073", "addr": "0075"}
        tables = {"t2": [
            {"column_name": "pan"},
            {"column_name": "name"},
            {"column_name": "addr"},
        ]}
        refined = refine_elements(existing, gt, tables)
        payment_des = [e for e in refined.elements if e.name == "PaymentCard"]
        assert len(payment_des) == 1  # no duplicate

    def test_preserves_existing(self):
        from sigint.data_element import DataElement, DataElementMember
        existing = DataElementCatalog(elements=[
            DataElement("PersonName", "identity", "test", [
                DataElementMember("first_name", "t1"),
            ]),
        ])
        refined = refine_elements(existing, {}, {})
        assert len(refined.elements) == 1
        assert refined.elements[0].name == "PersonName"
