"""Classifier Protocol and Classification result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sigint.category_set import ReferenceCategory
from sigint.ontology import Category
from sigint.sampler import ColumnSample


@dataclass(frozen=True)
class Classification:
    """Result of classifying a single column."""

    category: Category | ReferenceCategory
    confidence: float
    evidence: str
    sensitivity_code: str | None = None
    boost: float = 0.0  # non-embedding score added (track as negative metric)

    @property
    def atlas_type_name(self) -> str:
        return self.category.atlas_type_name


class Classifier(Protocol):
    """Interface for column classifiers.

    Implementations must provide a ``classify`` method that inspects a
    ``ColumnSample`` and returns a ``Classification`` or ``None``.
    """

    def classify(
        self,
        sample: ColumnSample,
        siblings: list[ColumnSample] | None = None,
    ) -> Classification | None: ...
