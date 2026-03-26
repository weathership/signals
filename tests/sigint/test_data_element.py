"""Tests for Data Element abstraction."""

from __future__ import annotations

import json
from pathlib import Path

from sigint.data_element import DataElement, DataElementCatalog, DataElementMember


def _payment_card_element():
    return DataElement(
        name="PaymentCard",
        domain="finance",
        definition="Payment card attributes",
        members=[
            DataElementMember("card_number", "payments", "identifier"),
            DataElementMember("cvv", "payments", "attribute"),
            DataElementMember("expiry_date", "payments", "temporal"),
        ],
        source="discovered",
    )


def _address_element():
    return DataElement(
        name="PostalAddress",
        domain="contact",
        definition="Postal address components",
        members=[
            DataElementMember("street", "customers", "attribute"),
            DataElementMember("city", "customers", "attribute"),
            DataElementMember("zip_code", "customers", "attribute"),
        ],
    )


# ── DataElementMember ────────────────────────────────────────────


class TestDataElementMember:
    def test_frozen(self):
        m = DataElementMember("col", "tbl", "attribute")
        assert m.column_name == "col"
        assert m.source_table == "tbl"
        assert m.role == "attribute"

    def test_default_role(self):
        m = DataElementMember("col", "tbl")
        assert m.role == "attribute"


# ── DataElement ──────────────────────────────────────────────────


class TestDataElement:
    def test_tables_property(self):
        de = _payment_card_element()
        assert de.tables == {"payments"}

    def test_column_names_property(self):
        de = _payment_card_element()
        assert de.column_names == ["card_number", "cvv", "expiry_date"]

    def test_multi_table_element(self):
        de = DataElement(
            name="CrossTable",
            domain="test",
            definition="test",
            members=[
                DataElementMember("a", "table1"),
                DataElementMember("b", "table2"),
            ],
        )
        assert de.tables == {"table1", "table2"}

    def test_to_dict(self):
        de = _payment_card_element()
        d = de.to_dict()
        assert d["name"] == "PaymentCard"
        assert d["domain"] == "finance"
        assert len(d["members"]) == 3
        assert d["members"][0]["role"] == "identifier"

    def test_from_dict_round_trip(self):
        de = _payment_card_element()
        d = de.to_dict()
        de2 = DataElement.from_dict(d)
        assert de2.name == de.name
        assert de2.domain == de.domain
        assert len(de2.members) == len(de.members)
        assert de2.members[0].column_name == "card_number"
        assert de2.members[0].role == "identifier"


# ── DataElementCatalog ───────────────────────────────────────────


class TestDataElementCatalog:
    def test_for_table(self):
        cat = DataElementCatalog(elements=[_payment_card_element(), _address_element()])
        result = cat.for_table("payments")
        assert len(result) == 1
        assert result[0].name == "PaymentCard"

    def test_for_table_empty(self):
        cat = DataElementCatalog(elements=[_payment_card_element()])
        assert cat.for_table("nonexistent") == []

    def test_for_column(self):
        cat = DataElementCatalog(elements=[_payment_card_element(), _address_element()])
        result = cat.for_column("card_number", "payments")
        assert len(result) == 1
        assert result[0].name == "PaymentCard"

    def test_for_column_wrong_table(self):
        cat = DataElementCatalog(elements=[_payment_card_element()])
        assert cat.for_column("card_number", "wrong_table") == []

    def test_json_round_trip(self):
        cat = DataElementCatalog(elements=[_payment_card_element(), _address_element()])
        json_str = cat.to_json()
        data = json.loads(json_str)
        cat2 = DataElementCatalog.from_dict(data)
        assert len(cat2.elements) == 2
        assert cat2.elements[0].name == "PaymentCard"
        assert cat2.elements[1].name == "PostalAddress"

    def test_to_dict(self):
        cat = DataElementCatalog(elements=[_payment_card_element()])
        d = cat.to_dict()
        assert "elements" in d
        assert len(d["elements"]) == 1

    def test_write_and_read(self, tmp_path):
        cat = DataElementCatalog(elements=[_payment_card_element()])
        out = tmp_path / "de.json"
        cat.write(out)
        cat2 = DataElementCatalog.from_json(out)
        assert len(cat2.elements) == 1
        assert cat2.elements[0].name == "PaymentCard"

    def test_empty_catalog(self):
        cat = DataElementCatalog()
        assert cat.elements == []
        assert cat.for_table("any") == []
