"""Taxonomy-agnostic category sets for column type annotation (CTA).

Supports both the SIGDG ontology and the annotations.csv taxonomy as
independent label sets.  Each taxonomy is represented as a ``CategorySet``
containing ``ReferenceCategory`` instances.

``HierarchicalCategorySet`` extends ``CategorySet`` with tree navigation
for Dempster-Shafer belief functions.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path


@dataclass(frozen=True)
class ReferenceCategory:
    """A single category in any taxonomy."""

    code: str  # "0085" (SIGDG) or "1.1.1.1.1.1.1" (annotation)
    label: str  # "TaxIdentifier" or "Payment Card Number"
    embedding_text: str  # pre-built text for the embedding model
    abbrev: str = ""  # "TIN" or "PAN"
    description: str = ""
    taxonomy: str = ""  # "sigdg" or "annotations"
    parent_code: str | None = None

    @property
    def atlas_type_name(self) -> str:
        if self.taxonomy == "sigdg":
            return f"SIGDG_{self.code}_{self.label}"
        safe = self.label.replace(" ", "").replace("/", "_")
        return f"ANN_{self.code.replace('.', '_')}_{safe}"


@dataclass
class CategorySet:
    """An ordered collection of reference categories for a taxonomy."""

    name: str
    categories: list[ReferenceCategory]

    @cached_property
    def by_code(self) -> dict[str, ReferenceCategory]:
        return {c.code: c for c in self.categories}

    @cached_property
    def by_abbrev(self) -> dict[str, ReferenceCategory]:
        return {c.abbrev: c for c in self.categories if c.abbrev}


class HierarchicalCategorySet(CategorySet):
    """A CategorySet with full parent→child tree navigation.

    ``categories`` (inherited) still returns leaf-only for backward compat.
    ``all_categories`` includes both leaves and internal (parent) nodes.
    """

    def __init__(
        self,
        name: str,
        categories: list[ReferenceCategory],
        all_categories: list[ReferenceCategory],
    ) -> None:
        super().__init__(name=name, categories=categories)
        self.all_categories = all_categories

    @cached_property
    def all_by_code(self) -> dict[str, ReferenceCategory]:
        """Lookup any node (leaf or internal) by code."""
        return {c.code: c for c in self.all_categories}

    @cached_property
    def parent(self) -> dict[str, str | None]:
        """code → parent_code mapping."""
        return {c.code: c.parent_code for c in self.all_categories}

    @cached_property
    def children(self) -> dict[str, list[str]]:
        """parent_code → list of direct child codes."""
        result: dict[str, list[str]] = {}
        for c in self.all_categories:
            if c.parent_code is not None:
                result.setdefault(c.parent_code, []).append(c.code)
        return result

    @cached_property
    def leaf_codes(self) -> frozenset[str]:
        """Codes with no children."""
        parents_with_children = set(self.children.keys())
        return frozenset(
            c.code for c in self.all_categories
            if c.code not in parents_with_children
        )

    def descendants(self, code: str) -> frozenset[str]:
        """All descendant leaf codes of *code*."""
        if code in self.leaf_codes:
            return frozenset({code})
        result: set[str] = set()
        stack = [code]
        while stack:
            current = stack.pop()
            for child in self.children.get(current, []):
                if child in self.leaf_codes:
                    result.add(child)
                else:
                    stack.append(child)
        return frozenset(result)

    def ancestors(self, code: str) -> list[str]:
        """Path from parent to root (does not include *code* itself)."""
        result: list[str] = []
        current = self.parent.get(code)
        while current is not None:
            result.append(current)
            current = self.parent.get(current)
        return result


# ── SIGDG factory ────────────────────────────────────────────────────


def _camel_to_words(name: str) -> str:
    """Split CamelCase into lowercase words."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()


def _build_sigdg_ref(c, taxonomy: str = "sigdg") -> ReferenceCategory:
    """Build a ReferenceCategory from a SIGDG ontology Category."""
    label_words = _camel_to_words(c.label)
    parts = [label_words]
    if c.abbrev:
        parts.append(c.abbrev)
    if c.description:
        parts.append(c.description)
    embedding_text = " | ".join(parts)
    return ReferenceCategory(
        code=c.code,
        label=c.label,
        embedding_text=embedding_text,
        abbrev=c.abbrev,
        description=c.description,
        taxonomy=taxonomy,
        parent_code=c.parent_code,
    )


def sigdg_category_set(*, hierarchical: bool = False) -> CategorySet:
    """Build a CategorySet from the SIGDG ontology.

    When *hierarchical* is True, returns a ``HierarchicalCategorySet``
    with the full parent→child tree.  Otherwise returns a flat
    ``CategorySet`` with leaf categories only.
    """
    from sigint.ontology import CATEGORIES

    parent_codes = {c.parent_code for c in CATEGORIES if c.parent_code}
    all_refs = [_build_sigdg_ref(c) for c in CATEGORIES]
    leaf_refs = [r for r in all_refs if r.code not in parent_codes]

    if not hierarchical:
        return CategorySet(name="sigdg", categories=leaf_refs)

    return HierarchicalCategorySet(
        name="sigdg",
        categories=leaf_refs,
        all_categories=all_refs,
    )


# ── Annotations factory ──────────────────────────────────────────────


def _build_annotation_parents(
    leaf_rows: list[dict],
) -> list[ReferenceCategory]:
    """Build synthetic parent ReferenceCategory nodes from dot-notation codes.

    For a leaf ``1.1.1.1.1.1.1`` generates parents:
    ``1.1.1.1.1.1``, ``1.1.1.1.1``, ..., ``1``.
    """
    existing_codes: set[str] = set()
    parents: dict[str, ReferenceCategory] = {}

    for row in leaf_rows:
        existing_codes.add(row["_id"])

    for row in leaf_rows:
        parts = row["_id"].split(".")
        for depth in range(1, len(parts)):
            parent_code = ".".join(parts[:depth])
            if parent_code in existing_codes or parent_code in parents:
                continue
            grandparent = ".".join(parts[:depth - 1]) if depth > 1 else None
            parents[parent_code] = ReferenceCategory(
                code=parent_code,
                label=f"Level{depth}_{parent_code}",
                embedding_text=f"level {depth} category {parent_code}",
                taxonomy="annotations",
                parent_code=grandparent,
            )

    return list(parents.values())


def annotation_category_set(
    csv_path: str | Path,
    *,
    hierarchical: bool = False,
) -> CategorySet:
    """Build a CategorySet from annotations.csv.

    Filters out deprecated rows and parent (non-leaf) rows.  Builds rich
    embedding text from: ``Annotation | Ontology label | Definition |
    Common Names``.

    When *hierarchical* is True, returns a ``HierarchicalCategorySet``
    with parent nodes derived from dot-notation prefixes.
    """
    _REQUIRED_COLUMNS = {"Ontology", "Annotation", "Definition"}

    csv_path = Path(csv_path)
    csv.field_size_limit(sys.maxsize)
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Detect ID column name — may have leading quote artifact
        id_col = "ID"
        if reader.fieldnames:
            for fn in reader.fieldnames:
                if fn.strip("' \ufeff") == "ID":
                    id_col = fn
                    break
            present = set(reader.fieldnames)
            missing = _REQUIRED_COLUMNS - present
            if missing:
                raise ValueError(
                    f"annotations.csv missing required columns: {missing}. "
                    f"Found: {sorted(present)}"
                )
        for row in reader:
            row_id = (row.get(id_col) or "").strip()
            if not row_id or not row_id[0].isdigit():
                continue
            row["_id"] = row_id
            rows.append(row)

    # Collect all IDs for leaf detection
    all_ids = {r["_id"] for r in rows}

    def _is_leaf(row_id: str) -> bool:
        prefix = row_id + "."
        return not any(
            other_id.startswith(prefix) and other_id != row_id
            for other_id in all_ids
        )

    leaf_rows: list[dict] = []
    refs = []
    for row in rows:
        row_id = row["_id"]
        deprecated = (row.get("Deprecated") or "").strip().lower()
        if deprecated == "yes":
            continue
        if not _is_leaf(row_id):
            continue

        leaf_rows.append(row)
        ontology = (row.get("Ontology") or "").strip()
        annotation = (row.get("Annotation") or "").strip()
        definition = (row.get("Definition") or "").strip()
        common_names = (row.get("Common Names") or "").strip()
        specifics = (row.get("Specifics, Examples and/or Additional Context") or "").strip()

        snake_label = re.sub(
            r"[^a-z0-9 ]", "",
            ontology.lower().replace("/", " ").replace("(", "").replace(")", ""),
        ).strip().replace(" ", "_")
        words_label = snake_label.replace("_", " ")
        parts = [words_label, ontology]
        if annotation:
            parts.append(annotation)
        if definition:
            parts.append(definition)
        if common_names:
            parts.append(common_names)
        if specifics:
            spec_short = specifics[:150]
            parts.append(spec_short)
        embedding_text = " | ".join(parts)

        # Derive parent_code from dot notation
        id_parts = row_id.rsplit(".", 1)
        parent_code = id_parts[0] if len(id_parts) > 1 else None

        refs.append(ReferenceCategory(
            code=row_id,
            label=ontology,
            embedding_text=embedding_text,
            abbrev=annotation,
            description=definition,
            taxonomy="annotations",
            parent_code=parent_code,
        ))

    if not hierarchical:
        return CategorySet(name="annotations", categories=refs)

    # Build parent nodes and collect non-deprecated non-leaf rows as parents too
    parent_refs_from_csv: list[ReferenceCategory] = []
    for row in rows:
        row_id = row["_id"]
        deprecated = (row.get("Deprecated") or "").strip().lower()
        if deprecated == "yes":
            continue
        if _is_leaf(row_id):
            continue  # already in refs
        ontology = (row.get("Ontology") or "").strip()
        id_parts = row_id.rsplit(".", 1)
        parent_code = id_parts[0] if len(id_parts) > 1 else None
        parent_refs_from_csv.append(ReferenceCategory(
            code=row_id,
            label=ontology or f"Level_{row_id}",
            embedding_text=ontology or row_id,
            taxonomy="annotations",
            parent_code=parent_code,
        ))

    # Also generate synthetic parents for any missing intermediate levels
    synthetic_parents = _build_annotation_parents(leaf_rows)
    existing_codes = {r.code for r in refs} | {r.code for r in parent_refs_from_csv}
    extra_parents = [p for p in synthetic_parents if p.code not in existing_codes]

    all_categories = refs + parent_refs_from_csv + extra_parents

    return HierarchicalCategorySet(
        name="annotations",
        categories=refs,
        all_categories=all_categories,
    )


# ── Meta-tagging dataset helpers ─────────────────────────────────────

# Column-name prefixes that mark annotation/reference columns in the
# meta-tagging dataset — not real data columns.
_ANNOTATION_PREFIXES = (
    "attr_", "ref_", "code_", "var_", "key_", "val_",
    "data_", "field_", "col_", "item_",
)


def is_data_column(column_name: str) -> bool:
    """Return True if *column_name* is a real data column (not an annotation ref).

    This is specific to the meta-tagging CSV format where annotation columns
    use known prefixes (attr_, ref_, code_, etc.).  Not intended for general
    production column filtering.
    """
    bare = column_name.split(".")[-1]  # strip table prefix if present
    if bare == "row_id":
        return False
    return not any(bare.startswith(p) for p in _ANNOTATION_PREFIXES)


def extract_ground_truth(
    headers: list[str],
    category_set: CategorySet,
) -> dict[str, str]:
    """Extract ground truth mappings from CSV header pairing.

    In the meta-tagging dataset, each data column is immediately followed by
    an annotation column whose name encodes the annotation ID.  For example::

        personal_data.payment_card_number
        personal_data.attr_1_1_1_1_1_1_1    ← annotation ID 1.1.1.1.1.1.1

    Returns ``{bare_col_name: annotation_code}`` for every data column that
    has a paired annotation column whose code exists in the category set.
    """
    truth: dict[str, str] = {}

    for i, hdr in enumerate(headers):
        bare = hdr.split(".", 1)[-1] if "." in hdr else hdr
        if bare == "row_id":
            continue

        # Check if this is an annotation column
        matched_prefix = None
        for prefix in _ANNOTATION_PREFIXES:
            if bare.startswith(prefix):
                matched_prefix = prefix
                break

        if matched_prefix is not None:
            # This is an annotation column — extract annotation code
            suffix = bare[len(matched_prefix):]
            ann_code = suffix.replace("_", ".")

            # The data column is the one immediately before this annotation
            if i > 0:
                prev_hdr = headers[i - 1]
                prev_bare = prev_hdr.split(".", 1)[-1] if "." in prev_hdr else prev_hdr
                if prev_bare != "row_id" and not any(
                    prev_bare.startswith(p) for p in _ANNOTATION_PREFIXES
                ):
                    # Validate the annotation code exists in the category set
                    if ann_code in category_set.by_code:
                        truth[prev_bare] = ann_code

    return truth
