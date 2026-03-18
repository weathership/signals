"""Feature extraction for column classification.

Extracts 11 discrete, ablatable features from a ColumnSample to support
SAGE feature importance analysis and multi-method classification.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from sigint.sampler import ColumnSample

# ── Pattern detectors ────────────────────────────────────────────────

_PATTERNS: dict[str, re.Pattern] = {
    "email_pattern": re.compile(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    ),
    "phone_pattern": re.compile(
        r"^[\+]?[\d\s\-\(\)\.]{7,20}$"
    ),
    "ssn_pattern": re.compile(
        r"^\d{3}-\d{2}-\d{4}$"
    ),
    "ipv4_pattern": re.compile(
        r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    ),
    "uuid_pattern": re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    ),
    "date_iso_pattern": re.compile(
        r"^\d{4}-\d{2}-\d{2}"
    ),
    "url_pattern": re.compile(
        r"^https?://"
    ),
    "credit_card_pattern": re.compile(
        r"^\d{13,19}$"
    ),
}

FEATURE_NAMES: list[str] = [
    "column_name",
    "column_type",
    "sample_values",
    "cardinality",
    "null_ratio",
    "value_entropy",
    "pattern_signals",
    "avg_value_length",
    "numeric_ratio",
    "sibling_context",
    "source_table",
]


def detect_patterns(values: list[str]) -> list[str]:
    """Detect which value patterns are present in a sample."""
    if not values:
        return []
    hits: list[str] = []
    for name, pat in _PATTERNS.items():
        match_count = sum(1 for v in values if pat.match(v.strip()))
        if match_count >= max(1, len(values) // 3):
            hits.append(name)
    return sorted(hits)


def _shannon_entropy(values: list[str]) -> float:
    """Shannon entropy of value lengths (bits)."""
    if not values:
        return 0.0
    lengths = [len(v) for v in values]
    counts = Counter(lengths)
    total = len(lengths)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return round(entropy, 4)


def _numeric_ratio(values: list[str]) -> float:
    """Fraction of values parseable as a number."""
    if not values:
        return 0.0
    numeric = 0
    for v in values:
        v = v.strip()
        try:
            float(v.replace(",", ""))
            numeric += 1
        except (ValueError, OverflowError):
            pass
    return round(numeric / len(values), 4)


# ── ColumnFeatures ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ColumnFeatures:
    """Discrete, ablatable features extracted from a column sample.

    Each of the 11 features can be independently masked for SAGE analysis.
    """

    column_name_humanized: str
    column_type: str | None
    sample_values_text: str | None
    cardinality: int | None
    null_ratio: float | None
    value_entropy: float | None
    pattern_signals: list[str] = field(default_factory=list)
    avg_value_length: float | None = None
    numeric_ratio: float | None = None
    sibling_names: list[str] = field(default_factory=list)
    source_table: str | None = None

    @property
    def feature_names(self) -> list[str]:
        """Ordered list of 11 feature names."""
        return list(FEATURE_NAMES)

    def to_embedding_text(self, mask: dict[str, bool] | None = None) -> str:
        """Build embedding text from enabled features only.

        Args:
            mask: feature_name -> enabled.  None means all enabled.
                  This is the ablation hook for SAGE.

        Returns:
            Pipe-separated text string suitable for embedding.
        """

        def _enabled(name: str) -> bool:
            if mask is None:
                return True
            return mask.get(name, True)

        parts: list[str] = []

        if _enabled("column_name") and self.column_name_humanized:
            parts.append(self.column_name_humanized)

        if _enabled("column_type") and self.column_type:
            parts.append(self.column_type)

        if _enabled("sample_values") and self.sample_values_text:
            parts.append(self.sample_values_text)

        if _enabled("cardinality") and self.cardinality is not None:
            parts.append(f"cardinality={self.cardinality}")

        if _enabled("null_ratio") and self.null_ratio is not None and self.null_ratio > 0:
            parts.append(f"null_ratio={self.null_ratio:.2f}")

        if _enabled("value_entropy") and self.value_entropy is not None and self.value_entropy > 0:
            parts.append(f"entropy={self.value_entropy:.2f}")

        if _enabled("pattern_signals") and self.pattern_signals:
            parts.append("patterns: " + ", ".join(self.pattern_signals))

        if _enabled("avg_value_length") and self.avg_value_length is not None:
            parts.append(f"avg_len={self.avg_value_length:.1f}")

        if _enabled("numeric_ratio") and self.numeric_ratio is not None and self.numeric_ratio > 0:
            parts.append(f"numeric={self.numeric_ratio:.2f}")

        if _enabled("sibling_context") and self.sibling_names:
            parts.append("siblings: " + ", ".join(self.sibling_names[:5]))

        if _enabled("source_table") and self.source_table:
            parts.append(f"table={self.source_table}")

        return " | ".join(parts) if parts else ""

    def feature_value(self, name: str) -> str:
        """Return the text contribution of a single feature."""
        mask = {n: (n == name) for n in FEATURE_NAMES}
        return self.to_embedding_text(mask)


# ── Extraction ───────────────────────────────────────────────────────


def extract_features(
    sample: ColumnSample,
    siblings: list[ColumnSample] | None = None,
    source_table: str | None = None,
    max_values: int = 5,
) -> ColumnFeatures:
    """Extract ColumnFeatures from a ColumnSample.

    Args:
        sample: The column to extract features from.
        siblings: Other columns in the same table (for context).
        source_table: Name of the source table.
        max_values: Max sample values to include in text.

    Returns:
        A frozen ColumnFeatures instance.
    """
    # Humanize column name
    name_humanized = sample.column_name.replace("_", " ")

    # Suppress uninformative types
    col_type: str | None = None
    if sample.column_type and sample.column_type.upper() not in ("STRING", "VARCHAR"):
        col_type = sample.column_type.lower()

    # Sample values text
    values = sample.values or []
    sample_text: str | None = None
    if values:
        sample_text = ", ".join(v[:80] for v in values[:max_values])

    # Cardinality (distinct values in the sample)
    cardinality = len(set(values)) if values else None

    # Null ratio
    null_ratio: float | None = None
    if sample.total_count > 0:
        null_ratio = round(sample.null_count / sample.total_count, 4)

    # Value entropy
    entropy = _shannon_entropy(values) if values else None

    # Pattern detection
    patterns = detect_patterns(values)

    # Average value length
    avg_len: float | None = None
    if values:
        avg_len = round(sum(len(v) for v in values) / len(values), 2)

    # Numeric ratio
    num_ratio = _numeric_ratio(values) if values else None

    # Sibling names (humanized)
    sibling_names: list[str] = []
    if siblings:
        sibling_names = [
            s.column_name.replace("_", " ")
            for s in siblings
            if s.column_name != sample.column_name
        ]

    return ColumnFeatures(
        column_name_humanized=name_humanized,
        column_type=col_type,
        sample_values_text=sample_text,
        cardinality=cardinality,
        null_ratio=null_ratio,
        value_entropy=entropy,
        pattern_signals=patterns,
        avg_value_length=avg_len,
        numeric_ratio=num_ratio,
        sibling_names=sibling_names,
        source_table=source_table,
    )
