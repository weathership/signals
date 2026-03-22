"""Vocabulary mapping between user-specific labels and SIGDG codes.

A mapping file bridges user terminology to the SIGDG ontology::

    {
      "source_taxonomy": "customer_vocab",
      "target_taxonomy": "sigdg",
      "mappings": {
        "Credit Card Number": "0085",
        "PAN": "0085",
        "Social Security Number": "0083",
        "SSN": "0083",
        "Email Address": "0072"
      }
    }

Usage::

    mapping = VocabMapping.from_file("config/sigint/my_mapping.json")
    code = mapping.resolve("PAN")  # -> "0085"
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VocabMapping:
    """Bidirectional vocabulary mapping."""

    source_taxonomy: str = ""
    target_taxonomy: str = "sigdg"
    mappings: dict[str, str] = field(default_factory=dict)

    def resolve(self, user_label: str) -> str | None:
        """Resolve a user label to a target taxonomy code.

        Tries exact match first, then case-insensitive.
        """
        if user_label in self.mappings:
            return self.mappings[user_label]

        lower = user_label.lower()
        for key, code in self.mappings.items():
            if key.lower() == lower:
                return code

        return None

    @classmethod
    def from_file(cls, path: str | Path) -> VocabMapping:
        """Load a mapping from a JSON file."""
        path = Path(path)
        with open(path) as f:
            data = json.load(f)

        return cls(
            source_taxonomy=data.get("source_taxonomy", ""),
            target_taxonomy=data.get("target_taxonomy", "sigdg"),
            mappings=data.get("mappings", data),
        )
