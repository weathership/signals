"""LLM backend abstraction for bootstrap classification.

Provides a unified interface for LLM calls supporting:
- Anthropic (Claude) via the anthropic SDK
- OpenAI-compatible (vLLM/Devstral) via the openai SDK
- Cerebras (GLM-4.7) via the OpenAI-compatible SDK with reasoning controls

Each backend converts batch column metadata into structured
classification responses with token tracking for cost estimation.
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sigint.sampler import ColumnSample

logger = logging.getLogger(__name__)

# ── Cerebras Cloud defaults ─────────────────────────────────────

CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
CEREBRAS_DEFAULT_MODEL = "zai-glm-4.7"


# ── Response types ───────────────────────────────────────────────


@dataclass(frozen=True)
class ColumnClassification:
    """Single column classification from an LLM."""

    column_name: str
    category_code: str | None
    confidence: float
    evidence: str
    alternatives: list[dict] = field(default_factory=list)  # [{code, confidence}, ...]


@dataclass(frozen=True)
class LLMResponse:
    """Batch response from an LLM backend."""

    classifications: list[ColumnClassification]
    input_tokens: int
    output_tokens: int
    model: str
    finish_reason: str = "stop"

    @property
    def truncated(self) -> bool:
        """Whether response was truncated due to max_tokens limit."""
        return self.finish_reason == "length"


# ── Configuration ────────────────────────────────────────────────


@dataclass
class LLMBackendConfig:
    """Configuration for LLM backend."""

    backend: str = "anthropic"  # "anthropic" | "openai_compatible" | "cerebras"
    api_key: str | None = None
    model: str = "claude-opus-4-6"
    base_url: str | None = None  # e.g. "http://localhost:8000/v1"
    max_tokens: int = 65536
    temperature: float = 0.0
    batch_size: int = 10  # columns per LLM call
    max_retries: int = 3  # Retry on transient errors (429, 502, 503)
    retry_delay: float = 2.0  # Initial retry delay (exponential backoff)
    disable_reasoning: bool = False  # Cerebras GLM: skip chain-of-thought


# ── Prompt building ──────────────────────────────────────────────


def build_system_prompt(category_table: str) -> str:
    """Build the bootstrap classification system prompt.

    Args:
        category_table: Markdown table of leaf categories (code | label | description).
    """
    return (
        "You are a data governance classification engine. Your task is to "
        "classify database columns into taxonomy categories based on column "
        "name, data type, sample values, and sibling context.\n"
        "\n"
        "## Categories\n"
        "\n"
        f"{category_table}\n"
        "\n"
        "## Instructions\n"
        "\n"
        "- Classify each column into exactly ONE leaf category.\n"
        "- Consider column name, data type, sample values, and sibling columns.\n"
        "- If no category fits, set category_code to null.\n"
        "- Provide confidence 0.0–1.0 and brief evidence.\n"
        "- For each column, list up to 3 alternative categories with confidence.\n"
        "- Respond with ONLY a JSON array, no markdown fencing.\n"
        "\n"
        "## Response Format\n"
        "\n"
        '[{"column_name": "ssn", "category_code": "0085", "confidence": 0.95, '
        '"evidence": "SSN pattern", "alternatives": [{"code": "0013", "confidence": 0.03}]}]'
    )


def build_batch_user_prompt(
    samples: list[ColumnSample],
    siblings_map: dict[str, list[ColumnSample]],
    revisit_context: dict[str, dict] | None = None,
    table_name: str | None = None,
    data_elements: list | None = None,
) -> str:
    """Build a user prompt for a batch of columns.

    Args:
        samples: Columns to classify.
        siblings_map: {column_name: sibling ColumnSamples}.
        revisit_context: Optional per-column enrichment for revisit passes.
            Keys are column names, values are dicts with 'ml_prediction',
            'belief', 'plausibility', 'conflict', 'confusable', 'previous'.
        table_name: Optional table name for context header.
        data_elements: Optional list of DataElement objects relevant to this batch.
    """
    parts: list[str] = []

    # Table-level context header
    if table_name:
        parts.append(f"## Table: {table_name}\n")

    # Data element context
    if data_elements:
        de_lines = ["## Discovered Data Elements"]
        for de in data_elements:
            members = ", ".join(de.column_names[:10])
            de_lines.append(f"- **{de.name}** ({de.domain}): {de.definition} [{members}]")
        parts.append("\n".join(de_lines) + "\n")

    for i, sample in enumerate(samples, 1):
        revisit = revisit_context.get(sample.column_name) if revisit_context else None
        tag = " (REVISIT)" if revisit else ""
        lines = [f"### Column {i}: {sample.column_name}{tag}"]
        lines.append(f"Type: {sample.column_type}")

        if sample.values:
            preview = sample.values[:10]
            lines.append(f"Values: {preview}")

        siblings = siblings_map.get(sample.column_name, [])
        sibling_names = [
            s.column_name for s in siblings if s.column_name != sample.column_name
        ]
        if sibling_names:
            lines.append(f"Siblings: {sibling_names}")

        if data_elements:
            col_des = [de for de in data_elements if sample.column_name in de.column_names]
            if col_des:
                lines.append(f"Data elements: {[de.name for de in col_des]}")

        if revisit:
            ml_pred = revisit.get("ml_prediction", "")
            bel = revisit.get("belief", 0.0)
            pl = revisit.get("plausibility", 0.0)
            k = revisit.get("conflict", 0.0)
            lines.append(f"ML prediction: {ml_pred} [Bel={bel:.2f}, Pl={pl:.2f}, K={k:.2f}]")
            if revisit.get("confusable"):
                lines.append(f"Confusable: {revisit['confusable']}")
            if revisit.get("previous"):
                prev = revisit["previous"]
                lines.append(
                    f"Your previous: {prev.get('code', '?')} (conf={prev.get('confidence', 0):.2f})"
                )

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _parse_classifications(text: str, expected_names: list[str]) -> list[ColumnClassification]:
    """Parse LLM JSON response into ColumnClassification list.

    Handles markdown fencing, partial JSON, and single-object responses.
    Falls back to regex extraction for non-JSON-compliant responses.
    """
    # Strip markdown fencing
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

    # Try direct JSON parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            return _dicts_to_classifications(data, expected_names)
    except (json.JSONDecodeError, ValueError):
        pass

    # Regex fallback: extract JSON array or objects
    array_match = re.search(r"\[[\s\S]*\]", cleaned)
    if array_match:
        try:
            data = json.loads(array_match.group())
            if isinstance(data, list):
                return _dicts_to_classifications(data, expected_names)
        except (json.JSONDecodeError, ValueError):
            pass

    # Last resort: extract individual JSON objects
    results = []
    for obj_match in re.finditer(r"\{[^{}]*\}", cleaned):
        try:
            d = json.loads(obj_match.group())
            results.append(d)
        except (json.JSONDecodeError, ValueError):
            continue

    if results:
        return _dicts_to_classifications(results, expected_names)

    logger.warning("Failed to parse LLM response: %s", text[:200])
    return []


def _dicts_to_classifications(
    data: list[dict], expected_names: list[str],
) -> list[ColumnClassification]:
    """Convert parsed dicts to ColumnClassification objects."""
    results = []
    for i, item in enumerate(data):
        name = item.get("column_name", "")
        if not name and i < len(expected_names):
            name = expected_names[i]

        alternatives = []
        for alt in item.get("alternatives", []):
            if isinstance(alt, dict) and "code" in alt:
                alternatives.append({
                    "code": str(alt["code"]),
                    "confidence": float(alt.get("confidence", 0.0)),
                })

        results.append(ColumnClassification(
            column_name=str(name),
            category_code=item.get("category_code"),
            confidence=float(item.get("confidence", 0.0)),
            evidence=str(item.get("evidence", "")),
            alternatives=alternatives,
        ))
    return results


# ── Abstract backend ─────────────────────────────────────────────


class LLMBackend(ABC):
    """Abstract LLM backend for batch column classification."""

    def __init__(self, config: LLMBackendConfig) -> None:
        self._config = config

    @abstractmethod
    def classify_batch(
        self,
        samples: list[ColumnSample],
        siblings_map: dict[str, list[ColumnSample]],
        system_prompt: str,
        revisit_context: dict[str, dict] | None = None,
        _user_prompt_override: str | None = None,
    ) -> LLMResponse:
        """Classify a batch of columns.

        Args:
            samples: Columns to classify (up to batch_size).
            siblings_map: Sibling columns per column name.
            system_prompt: Pre-built system prompt with category table.
            revisit_context: Optional enrichment for revisit passes.
            _user_prompt_override: Pre-built user prompt (bypasses default
                prompt building).  Used by the bootstrap agent to inject
                table and data-element context.
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Verify the backend is reachable and functional."""


# ── Anthropic backend ────────────────────────────────────────────


class AnthropicBackend(LLMBackend):
    """Backend using the Anthropic Messages API (Claude)."""

    def __init__(self, config: LLMBackendConfig) -> None:
        super().__init__(config)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package required. Install with: uv add anthropic"
            )

        if not self._config.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY in .env."
            )

        self._client = anthropic.Anthropic(api_key=self._config.api_key)
        return self._client

    def classify_batch(
        self,
        samples: list[ColumnSample],
        siblings_map: dict[str, list[ColumnSample]],
        system_prompt: str,
        revisit_context: dict[str, dict] | None = None,
        _user_prompt_override: str | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        user_prompt = _user_prompt_override or build_batch_user_prompt(
            samples, siblings_map, revisit_context,
        )
        expected_names = [s.column_name for s in samples]

        response = client.messages.create(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = response.content[0].text.strip()
        classifications = _parse_classifications(text, expected_names)

        return LLMResponse(
            classifications=classifications,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self._config.model,
        )

    def health_check(self) -> bool:
        try:
            client = self._get_client()
            resp = client.messages.create(
                model=self._config.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return len(resp.content) > 0
        except Exception:
            return False


# ── OpenAI-compatible backend ────────────────────────────────────


class OpenAICompatibleBackend(LLMBackend):
    """Backend using OpenAI-compatible API (vLLM, Devstral, etc.)."""

    def __init__(self, config: LLMBackendConfig) -> None:
        super().__init__(config)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai package required. Install with: uv add openai"
            )

        kwargs = {}
        if self._config.api_key:
            kwargs["api_key"] = self._config.api_key
        else:
            # vLLM local servers often don't require a key
            kwargs["api_key"] = "EMPTY"

        if self._config.base_url:
            kwargs["base_url"] = self._config.base_url

        self._client = openai.OpenAI(**kwargs)
        return self._client

    def classify_batch(
        self,
        samples: list[ColumnSample],
        siblings_map: dict[str, list[ColumnSample]],
        system_prompt: str,
        revisit_context: dict[str, dict] | None = None,
        _user_prompt_override: str | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        user_prompt = _user_prompt_override or build_batch_user_prompt(
            samples, siblings_map, revisit_context,
        )
        expected_names = [s.column_name for s in samples]

        api_params: dict = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        # Cerebras GLM reasoning controls (via extra_body)
        if self._config.disable_reasoning:
            api_params["extra_body"] = {"disable_reasoning": True}

        # Retry loop with exponential backoff for transient errors
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries):
            try:
                response = client.chat.completions.create(**api_params)
                break
            except Exception as e:
                last_error = e
                err_str = str(e)
                retryable = any(code in err_str for code in ("429", "502", "503", "504"))
                if retryable and attempt < self._config.max_retries - 1:
                    delay = self._config.retry_delay * (2 ** attempt)
                    logger.warning(
                        "Transient error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, self._config.max_retries, delay, e,
                    )
                    time.sleep(delay)
                    continue
                raise
        else:
            raise last_error  # type: ignore[misc]

        text = response.choices[0].message.content or ""
        text = text.strip()

        # Extract response metadata
        finish_reason = response.choices[0].finish_reason or "stop"
        input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(response.usage, "completion_tokens", 0) or 0
        reasoning_tokens = 0
        if response.usage and response.usage.completion_tokens_details:
            reasoning_tokens = getattr(
                response.usage.completion_tokens_details, "reasoning_tokens", 0
            ) or 0

        # Log truncation as a warning (actionable signal)
        if finish_reason == "length":
            logger.warning(
                "LLM response TRUNCATED: %d chars, in=%d, out=%d "
                "(reasoning=%d, max_tokens=%d) — increase max_tokens or reduce batch size",
                len(text), input_tokens, output_tokens,
                reasoning_tokens, self._config.max_tokens,
            )
        else:
            logger.info(
                "LLM response: %d chars, finish=%s, in=%d, out=%d (reasoning=%d)",
                len(text), finish_reason, input_tokens, output_tokens, reasoning_tokens,
            )

        classifications = _parse_classifications(text, expected_names)

        return LLMResponse(
            classifications=classifications,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._config.model,
            finish_reason=finish_reason,
        )

    def health_check(self) -> bool:
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self._config.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return len(resp.choices) > 0
        except Exception:
            return False


# ── Factory ──────────────────────────────────────────────────────


def create_backend(config: LLMBackendConfig) -> LLMBackend:
    """Create an LLM backend from configuration.

    Args:
        config: Backend configuration specifying type and credentials.

    Returns:
        Configured LLMBackend instance.

    Raises:
        ValueError: If backend type is unknown.
    """
    if config.backend == "anthropic":
        return AnthropicBackend(config)
    if config.backend == "openai_compatible":
        return OpenAICompatibleBackend(config)
    if config.backend == "cerebras":
        cerebras_config = LLMBackendConfig(
            backend="cerebras",
            api_key=config.api_key,
            model=config.model if config.model != "claude-opus-4-6" else CEREBRAS_DEFAULT_MODEL,
            base_url=config.base_url or CEREBRAS_BASE_URL,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            batch_size=config.batch_size,
            max_retries=config.max_retries,
            retry_delay=config.retry_delay,
            disable_reasoning=config.disable_reasoning,
        )
        return OpenAICompatibleBackend(cerebras_config)
    raise ValueError(
        f"Unknown LLM backend: {config.backend!r}. "
        f"Use 'anthropic', 'openai_compatible', or 'cerebras'."
    )
