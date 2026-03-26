"""Data Element abstraction for composite semantic concepts.

A Data Element groups related columns across one or more tables into a
reusable governance concept.  Examples:

  - "PaymentCard" → card_number, cvv, expiry_date, cardholder_name
  - "BiospecimenCollection" → sample_location, specimen_type, instrument_id
  - "PostalAddress" → street, city, state, zip_code, country

Data Elements are discovered via schema analysis (naming conventions,
FK hints, category co-occurrence) and registered in Apache Atlas as
``sigint_data_element`` entities with column membership relationships.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DataElementMember:
    """A column that participates in a data element."""

    column_name: str
    source_table: str
    role: str = "attribute"  # "identifier" | "attribute" | "temporal" | "reference"


@dataclass
class DataElement:
    """A reusable semantic concept spanning columns across tables."""

    name: str  # e.g. "PaymentCard", "BiospecimenCollection"
    domain: str  # e.g. "finance", "healthcare", "identity"
    definition: str  # human-readable description
    members: list[DataElementMember] = field(default_factory=list)
    source: str = "discovered"  # "discovered" | "defined" | "llm"

    @property
    def tables(self) -> set[str]:
        """Unique tables that contribute members."""
        return {m.source_table for m in self.members}

    @property
    def column_names(self) -> list[str]:
        """Ordered list of member column names."""
        return [m.column_name for m in self.members]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "domain": self.domain,
            "definition": self.definition,
            "source": self.source,
            "members": [
                {
                    "column_name": m.column_name,
                    "source_table": m.source_table,
                    "role": m.role,
                }
                for m in self.members
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> DataElement:
        members = [
            DataElementMember(
                column_name=m["column_name"],
                source_table=m["source_table"],
                role=m.get("role", "attribute"),
            )
            for m in data.get("members", [])
        ]
        return cls(
            name=data["name"],
            domain=data.get("domain", ""),
            definition=data.get("definition", ""),
            members=members,
            source=data.get("source", "discovered"),
        )


@dataclass
class DataElementCatalog:
    """Registry of all discovered/defined data elements."""

    elements: list[DataElement] = field(default_factory=list)

    def for_table(self, table_name: str) -> list[DataElement]:
        """Return elements that have at least one member in *table_name*."""
        return [e for e in self.elements if table_name in e.tables]

    def for_column(self, column_name: str, source_table: str) -> list[DataElement]:
        """Return elements that include a specific column."""
        return [
            e
            for e in self.elements
            if any(
                m.column_name == column_name and m.source_table == source_table
                for m in e.members
            )
        ]

    def to_dict(self) -> dict:
        return {"elements": [e.to_dict() for e in self.elements]}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())

    @classmethod
    def from_dict(cls, data: dict) -> DataElementCatalog:
        elements = [DataElement.from_dict(e) for e in data.get("elements", [])]
        return cls(elements=elements)

    @classmethod
    def from_json(cls, path: Path) -> DataElementCatalog:
        data = json.loads(path.read_text())
        return cls.from_dict(data)
