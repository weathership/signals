"""LLM-based column classifier using Claude via the Anthropic API."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from sigint.classifier import Classification
from sigint.ontology import CATEGORIES, CATEGORY_BY_CODE, DEFAULT_SENSITIVITY
from sigint.sampler import ColumnSample


@dataclass
class LLMClassifierConfig:
    """Configuration for the LLM classifier."""

    api_key: str | None = None
    model: str = "claude-opus-4-6"
    max_tokens: int = 1024
    annotations_vocabulary: list[dict] = field(default_factory=list)


class LLMClassifier:
    """Classify columns against SIGDG categories using Claude.

    Zero-shot classification: the full SIGDG category table is provided
    in the system prompt, and optional domain vocabulary (annotations.csv
    or similar) provides disambiguation context.
    """

    def __init__(self, config: LLMClassifierConfig) -> None:
        self._config = config
        self._client = None

    def _get_client(self):
        """Lazily initialize the Anthropic client."""
        if self._client is not None:
            return self._client

        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package required for LLM classification. "
                "Install with: pip install anthropic"
            )

        api_key = self._config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var "
                "or pass --api-key."
            )

        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def _build_system_prompt(self) -> str:
        """Build the system prompt with SIGDG category table."""
        lines = [
            "You are a data governance classification engine. Your task is to "
            "classify database columns into SIGDG (Signals Data Governance) "
            "categories based on column name, data type, and sample values.",
            "",
            "## SIGDG Categories",
            "",
            "| Code | Abbrev | Label | Description |",
            "|------|--------|-------|-------------|",
        ]

        # Only include leaf categories (the ones we actually classify into)
        leaf_codes = {c.code for c in CATEGORIES} - {
            c.parent_code for c in CATEGORIES if c.parent_code
        }
        for cat in CATEGORIES:
            if cat.code in leaf_codes:
                lines.append(
                    f"| {cat.code} | {cat.abbrev} | {cat.label} | "
                    f"{cat.description} |"
                )

        lines.extend([
            "",
            "## Instructions",
            "",
            "- Classify the column into exactly ONE leaf category from the table above.",
            "- Consider column name, data type, sample values, and sibling columns for context.",
            "- If no category fits with reasonable confidence, respond with null.",
            "- Respond with ONLY a JSON object, no markdown fencing or explanation.",
            "",
            '## Response Format',
            '',
            '{"category_code": "0085", "confidence": 0.92, '
            '"evidence": "column name contains SSN, values match 9-digit pattern"}',
            "",
            "Fields:",
            '- "category_code": 4-digit SIGDG code from the table',
            '- "confidence": float 0.0–1.0',
            '- "evidence": brief explanation of classification rationale',
        ])

        if self._config.annotations_vocabulary:
            lines.extend([
                "",
                "## Reference Vocabulary (domain context)",
                "",
                "The following terms are from the deployment domain and may help "
                "disambiguate column meanings:",
                "",
            ])
            for entry in self._config.annotations_vocabulary[:50]:
                term = entry.get("annotation", entry.get("term", ""))
                desc = entry.get("description", "")
                if term:
                    lines.append(f"- **{term}**: {desc}")

        return "\n".join(lines)

    def _build_user_prompt(
        self,
        sample: ColumnSample,
        siblings: list[ColumnSample] | None = None,
    ) -> str:
        """Build the user prompt for a single column."""
        lines = [
            f"Column: {sample.column_name}",
            f"Type: {sample.column_type}",
        ]

        if sample.values:
            preview = sample.values[:10]
            lines.append(f"Sample values: {preview}")

        if siblings:
            sibling_names = [
                s.column_name for s in siblings
                if s.column_name != sample.column_name
            ]
            if sibling_names:
                lines.append(f"Sibling columns in same table: {sibling_names}")

        return "\n".join(lines)

    def classify(
        self,
        sample: ColumnSample,
        siblings: list[ColumnSample] | None = None,
    ) -> Classification | None:
        """Classify a column sample against SIGDG categories."""
        client = self._get_client()

        response = client.messages.create(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=self._build_system_prompt(),
            messages=[{
                "role": "user",
                "content": self._build_user_prompt(sample, siblings),
            }],
        )

        text = response.content[0].text.strip()
        return self._parse_response(text)

    def _parse_response(self, text: str) -> Classification | None:
        """Parse the LLM JSON response into a Classification."""
        # Strip markdown fencing if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

        if data is None:
            return None

        code = data.get("category_code")
        confidence = data.get("confidence", 0.0)
        evidence = data.get("evidence", "")

        if not code or code not in CATEGORY_BY_CODE:
            return None

        cat = CATEGORY_BY_CODE[code]
        return Classification(
            category=cat,
            confidence=round(float(confidence), 3),
            evidence=str(evidence),
            sensitivity_code=DEFAULT_SENSITIVITY.get(code),
        )


def load_annotations(path: str | Path) -> list[dict]:
    """Load a vocabulary CSV (annotations.csv or similar) as list of dicts."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows
