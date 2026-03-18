"""Taxonomy-agnostic category sets for column type annotation (CTA).

Supports both the SIGDG ontology and the annotations.csv taxonomy as
independent label sets.  Each taxonomy is represented as a ``CategorySet``
containing ``ReferenceCategory`` instances.
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


# ── SIGDG factory ────────────────────────────────────────────────────


def _camel_to_words(name: str) -> str:
    """Split CamelCase into lowercase words."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()


def sigdg_category_set() -> CategorySet:
    """Build a CategorySet from the SIGDG ontology (leaf categories only)."""
    from sigint.ontology import CATEGORIES

    parent_codes = {c.parent_code for c in CATEGORIES if c.parent_code}
    leaves = [c for c in CATEGORIES if c.code not in parent_codes]

    refs = []
    for c in leaves:
        label_words = _camel_to_words(c.label)
        parts = [label_words]
        if c.abbrev:
            parts.append(c.abbrev)
        if c.description:
            parts.append(c.description)
        embedding_text = " | ".join(parts)
        refs.append(ReferenceCategory(
            code=c.code,
            label=c.label,
            embedding_text=embedding_text,
            abbrev=c.abbrev,
            description=c.description,
            taxonomy="sigdg",
        ))
    return CategorySet(name="sigdg", categories=refs)


# ── Annotations factory ──────────────────────────────────────────────


def annotation_category_set(csv_path: str | Path) -> CategorySet:
    """Build a CategorySet from annotations.csv.

    Filters out deprecated rows and parent (non-leaf) rows.  Builds rich
    embedding text from: ``Annotation | Ontology label | Definition |
    Common Names``.
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

    refs = []
    for row in rows:
        row_id = row["_id"]
        deprecated = (row.get("Deprecated") or "").strip().lower()
        if deprecated == "yes":
            continue
        if not _is_leaf(row_id):
            continue

        ontology = (row.get("Ontology") or "").strip()
        annotation = (row.get("Annotation") or "").strip()
        definition = (row.get("Definition") or "").strip()
        common_names = (row.get("Common Names") or "").strip()
        specifics = (row.get("Specifics, Examples and/or Additional Context") or "").strip()

        # Build embedding text optimized for cosine matching against
        # column names (snake_case humanized) with sample values.
        # Front-load the most discriminating terms:
        # 1. Snake-case label (matches column name format exactly)
        # 2. Ontology label (human readable)
        # 3. Annotation code (matches annotation column conventions)
        # 4. Definition (provides semantic context)
        # 5. Common Names (aliases and synonyms)
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

        refs.append(ReferenceCategory(
            code=row_id,
            label=ontology,
            embedding_text=embedding_text,
            abbrev=annotation,
            description=definition,
            taxonomy="annotations",
        ))

    return CategorySet(name="annotations", categories=refs)


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
