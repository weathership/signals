"""Tests for LLM backend abstraction (all API calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sigint.llm_backend import (
    AnthropicBackend,
    LLMBackendConfig,
    LLMResponse,
    OpenAICompatibleBackend,
    _parse_classifications,
    build_batch_user_prompt,
    build_system_prompt,
    create_backend,
)
from sigint.sampler import ColumnSample


def _make_sample(name="ssn", col_type="STRING", values=None):
    return ColumnSample(
        column_name=name,
        column_type=col_type,
        values=values or ["123-45-6789", "987-65-4321"],
    )


# ── Prompt building ──────────────────────────────────────────────


class TestBuildSystemPrompt:
    def test_contains_category_table(self):
        table = "| 0085 | TaxIdentifier | SSN/TIN |\n| 0076 | EmailAddress | Email |"
        prompt = build_system_prompt(table)
        assert "TaxIdentifier" in prompt
        assert "EmailAddress" in prompt
        assert "JSON array" in prompt

    def test_contains_response_format(self):
        prompt = build_system_prompt("| Code | Label |")
        assert "alternatives" in prompt
        assert "category_code" in prompt


class TestBuildBatchUserPrompt:
    def test_single_column(self):
        samples = [_make_sample("email", "STRING", ["a@b.com"])]
        prompt = build_batch_user_prompt(samples, {})
        assert "### Column 1: email" in prompt
        assert "STRING" in prompt
        assert "a@b.com" in prompt

    def test_multiple_columns(self):
        samples = [_make_sample("email"), _make_sample("phone")]
        prompt = build_batch_user_prompt(samples, {})
        assert "### Column 1: email" in prompt
        assert "### Column 2: phone" in prompt

    def test_siblings_included(self):
        samples = [_make_sample("ssn")]
        siblings = {"ssn": [_make_sample("first_name"), _make_sample("phone")]}
        prompt = build_batch_user_prompt(samples, siblings)
        assert "first_name" in prompt
        assert "phone" in prompt

    def test_table_name_in_prompt(self):
        samples = [_make_sample("ssn")]
        prompt = build_batch_user_prompt(samples, {}, table_name="customers")
        assert "## Table: customers" in prompt
        assert "### Column 1: ssn" in prompt

    def test_table_name_none_no_header(self):
        samples = [_make_sample("ssn")]
        prompt = build_batch_user_prompt(samples, {}, table_name=None)
        assert "## Table:" not in prompt

    def test_data_elements_in_prompt(self):
        from sigint.data_element import DataElement, DataElementMember
        samples = [_make_sample("card_number")]
        de = DataElement(
            name="PaymentCard", domain="finance",
            definition="Payment card attributes",
            members=[DataElementMember("card_number", "payments")],
        )
        prompt = build_batch_user_prompt(samples, {}, data_elements=[de])
        assert "## Discovered Data Elements" in prompt
        assert "PaymentCard" in prompt
        assert "Data elements: ['PaymentCard']" in prompt

    def test_data_elements_none_no_section(self):
        samples = [_make_sample("ssn")]
        prompt = build_batch_user_prompt(samples, {}, data_elements=None)
        assert "Data Elements" not in prompt

    def test_revisit_context(self):
        samples = [_make_sample("account_number")]
        revisit = {
            "account_number": {
                "ml_prediction": "BankAccountNumber",
                "belief": 0.35,
                "plausibility": 0.68,
                "conflict": 0.31,
                "confusable": "BankAccountNumber / PaymentAccountNumber",
                "previous": {"code": "0070", "confidence": 0.65},
            },
        }
        prompt = build_batch_user_prompt(samples, {}, revisit_context=revisit)
        assert "(REVISIT)" in prompt
        assert "BankAccountNumber" in prompt
        assert "Bel=0.35" in prompt
        assert "K=0.31" in prompt
        assert "Confusable:" in prompt
        assert "Your previous:" in prompt


# ── Response parsing ─────────────────────────────────────────────


class TestParseClassifications:
    def test_valid_json_array(self):
        text = (
            '[{"column_name": "ssn", "category_code": "0085", '
            '"confidence": 0.95, "evidence": "SSN pattern", '
            '"alternatives": [{"code": "0013", "confidence": 0.03}]}]'
        )
        results = _parse_classifications(text, ["ssn"])
        assert len(results) == 1
        assert results[0].column_name == "ssn"
        assert results[0].category_code == "0085"
        assert results[0].confidence == 0.95
        assert len(results[0].alternatives) == 1

    def test_single_object(self):
        text = '{"column_name": "email", "category_code": "0076", "confidence": 0.88, "evidence": "email"}'
        results = _parse_classifications(text, ["email"])
        assert len(results) == 1
        assert results[0].category_code == "0076"

    def test_markdown_fencing(self):
        text = '```json\n[{"column_name": "x", "category_code": "0085", "confidence": 0.9, "evidence": "x"}]\n```'
        results = _parse_classifications(text, ["x"])
        assert len(results) == 1

    def test_fills_missing_name_from_expected(self):
        text = '[{"category_code": "0085", "confidence": 0.9, "evidence": "x"}]'
        results = _parse_classifications(text, ["ssn"])
        assert results[0].column_name == "ssn"

    def test_garbage_returns_empty(self):
        results = _parse_classifications("I don't know what this is", ["x"])
        assert results == []

    def test_regex_fallback_extracts_objects(self):
        text = 'Here are my results: {"column_name": "x", "category_code": "0085", "confidence": 0.9, "evidence": "test"}'
        results = _parse_classifications(text, ["x"])
        assert len(results) == 1
        assert results[0].category_code == "0085"

    def test_null_category_code(self):
        text = '[{"column_name": "x", "category_code": null, "confidence": 0.1, "evidence": "unclear"}]'
        results = _parse_classifications(text, ["x"])
        assert len(results) == 1
        assert results[0].category_code is None


# ── Anthropic backend ────────────────────────────────────────────


def _mock_anthropic_response(text: str, input_tokens=100, output_tokens=50):
    content_block = MagicMock()
    content_block.text = text
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    resp = MagicMock()
    resp.content = [content_block]
    resp.usage = usage
    return resp


class TestAnthropicBackend:
    def test_classify_batch(self):
        config = LLMBackendConfig(backend="anthropic", api_key="test-key")
        backend = AnthropicBackend(config)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            '[{"column_name": "ssn", "category_code": "0085", '
            '"confidence": 0.95, "evidence": "SSN", "alternatives": []}]'
        )
        backend._client = mock_client

        result = backend.classify_batch(
            [_make_sample()], {}, "system prompt"
        )
        assert isinstance(result, LLMResponse)
        assert len(result.classifications) == 1
        assert result.classifications[0].category_code == "0085"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.model == "claude-opus-4-6"

    def test_missing_api_key_raises(self):
        config = LLMBackendConfig(backend="anthropic", api_key=None)
        backend = AnthropicBackend(config)
        with pytest.raises((ValueError, ImportError)):
            backend._get_client()

    def test_health_check_success(self):
        config = LLMBackendConfig(backend="anthropic", api_key="test-key")
        backend = AnthropicBackend(config)
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response("pong")
        backend._client = mock_client
        assert backend.health_check() is True

    def test_health_check_failure(self):
        config = LLMBackendConfig(backend="anthropic", api_key="test-key")
        backend = AnthropicBackend(config)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("connection error")
        backend._client = mock_client
        assert backend.health_check() is False


# ── OpenAI-compatible backend ────────────────────────────────────


def _mock_openai_response(
    text: str,
    prompt_tokens=80,
    completion_tokens=40,
    finish_reason="stop",
    reasoning_tokens=0,
):
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason
    details = MagicMock()
    details.reasoning_tokens = reasoning_tokens
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.completion_tokens_details = details
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


class TestOpenAICompatibleBackend:
    def test_classify_batch(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="devstral-small-2",
        )
        backend = OpenAICompatibleBackend(config)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            '[{"column_name": "email", "category_code": "0076", '
            '"confidence": 0.88, "evidence": "email col", "alternatives": []}]'
        )
        backend._client = mock_client

        result = backend.classify_batch(
            [_make_sample("email")], {}, "system prompt"
        )
        assert len(result.classifications) == 1
        assert result.classifications[0].category_code == "0076"
        assert result.input_tokens == 80
        assert result.output_tokens == 40
        assert result.model == "devstral-small-2"

    def test_no_api_key_uses_empty(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            api_key=None,
            base_url="http://localhost:8000/v1",
        )
        backend = OpenAICompatibleBackend(config)
        mock_openai_mod = MagicMock()
        mock_openai_mod.OpenAI.return_value = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            # Force re-init
            backend._client = None
            backend._get_client()
            mock_openai_mod.OpenAI.assert_called_once_with(
                api_key="EMPTY", base_url="http://localhost:8000/v1"
            )

    def test_health_check_success(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("pong")
        backend._client = mock_client
        assert backend.health_check() is True

    def test_health_check_failure(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("timeout")
        backend._client = mock_client
        assert backend.health_check() is False


# ── Factory ──────────────────────────────────────────────────────


class TestCreateBackend:
    def test_anthropic(self):
        config = LLMBackendConfig(backend="anthropic", api_key="key")
        backend = create_backend(config)
        assert isinstance(backend, AnthropicBackend)

    def test_openai_compatible(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
        )
        backend = create_backend(config)
        assert isinstance(backend, OpenAICompatibleBackend)

    def test_cerebras(self):
        config = LLMBackendConfig(backend="cerebras", api_key="csk-test")
        backend = create_backend(config)
        assert isinstance(backend, OpenAICompatibleBackend)

    def test_cerebras_default_model(self):
        config = LLMBackendConfig(backend="cerebras", api_key="csk-test")
        backend = create_backend(config)
        assert backend._config.model == "zai-glm-4.7"

    def test_cerebras_custom_model(self):
        config = LLMBackendConfig(
            backend="cerebras", api_key="csk-test", model="llama-3.3-70b",
        )
        backend = create_backend(config)
        assert backend._config.model == "llama-3.3-70b"

    def test_cerebras_base_url(self):
        config = LLMBackendConfig(backend="cerebras", api_key="csk-test")
        backend = create_backend(config)
        assert backend._config.base_url == "https://api.cerebras.ai/v1"

    def test_cerebras_passes_retry_config(self):
        config = LLMBackendConfig(
            backend="cerebras", api_key="csk-test",
            max_retries=5, retry_delay=3.0,
        )
        backend = create_backend(config)
        assert backend._config.max_retries == 5
        assert backend._config.retry_delay == 3.0

    def test_cerebras_passes_disable_reasoning(self):
        config = LLMBackendConfig(
            backend="cerebras", api_key="csk-test", disable_reasoning=True,
        )
        backend = create_backend(config)
        assert backend._config.disable_reasoning is True

    def test_unknown_raises(self):
        config = LLMBackendConfig(backend="unknown")
        with pytest.raises(ValueError, match="Unknown LLM backend"):
            create_backend(config)


# ── Truncation detection ────────────────────────────────────────


class TestLLMResponseTruncation:
    def test_truncated_when_length(self):
        resp = LLMResponse(
            classifications=[], input_tokens=100, output_tokens=50,
            model="test", finish_reason="length",
        )
        assert resp.truncated is True

    def test_not_truncated_when_stop(self):
        resp = LLMResponse(
            classifications=[], input_tokens=100, output_tokens=50,
            model="test", finish_reason="stop",
        )
        assert resp.truncated is False

    def test_default_finish_reason_is_stop(self):
        resp = LLMResponse(
            classifications=[], input_tokens=100, output_tokens=50, model="test",
        )
        assert resp.finish_reason == "stop"
        assert resp.truncated is False


class TestOpenAITruncationTracking:
    def test_truncated_response_propagates_finish_reason(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="test-model",
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            '[{"column_name": "x", "category_code": "0085", '
            '"confidence": 0.9, "evidence": "test", "alternatives": []}]',
            finish_reason="length",
            reasoning_tokens=3000,
        )
        backend._client = mock_client

        result = backend.classify_batch([_make_sample()], {}, "system prompt")
        assert result.finish_reason == "length"
        assert result.truncated is True

    def test_normal_response_finish_reason_stop(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="test-model",
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            '[{"column_name": "ssn", "category_code": "0085", '
            '"confidence": 0.95, "evidence": "SSN", "alternatives": []}]',
        )
        backend._client = mock_client

        result = backend.classify_batch([_make_sample()], {}, "system prompt")
        assert result.finish_reason == "stop"
        assert result.truncated is False


# ── Retry with exponential backoff ──────────────────────────────


class TestOpenAIRetryLogic:
    def test_retries_on_429(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="test-model",
            max_retries=3,
            retry_delay=0.01,  # Fast for testing
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()

        # First call: 429, second call: success
        mock_client.chat.completions.create.side_effect = [
            Exception("Error code: 429 rate limit exceeded"),
            _mock_openai_response(
                '[{"column_name": "ssn", "category_code": "0085", '
                '"confidence": 0.9, "evidence": "SSN", "alternatives": []}]'
            ),
        ]
        backend._client = mock_client

        result = backend.classify_batch([_make_sample()], {}, "system prompt")
        assert len(result.classifications) == 1
        assert mock_client.chat.completions.create.call_count == 2

    def test_retries_on_502(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="test-model",
            max_retries=3,
            retry_delay=0.01,
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()

        mock_client.chat.completions.create.side_effect = [
            Exception("502 Bad Gateway"),
            _mock_openai_response(
                '[{"column_name": "ssn", "category_code": "0085", '
                '"confidence": 0.9, "evidence": "SSN", "alternatives": []}]'
            ),
        ]
        backend._client = mock_client

        result = backend.classify_batch([_make_sample()], {}, "system prompt")
        assert len(result.classifications) == 1

    def test_raises_after_max_retries(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="test-model",
            max_retries=2,
            retry_delay=0.01,
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()

        mock_client.chat.completions.create.side_effect = Exception(
            "Error code: 429 rate limit exceeded"
        )
        backend._client = mock_client

        with pytest.raises(Exception, match="429"):
            backend.classify_batch([_make_sample()], {}, "system prompt")
        assert mock_client.chat.completions.create.call_count == 2

    def test_non_retryable_error_raises_immediately(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="test-model",
            max_retries=3,
            retry_delay=0.01,
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()

        mock_client.chat.completions.create.side_effect = Exception(
            "401 Unauthorized: invalid API key"
        )
        backend._client = mock_client

        with pytest.raises(Exception, match="401"):
            backend.classify_batch([_make_sample()], {}, "system prompt")
        assert mock_client.chat.completions.create.call_count == 1


# ── Disable reasoning (Cerebras GLM) ───────────────────────────


class TestDisableReasoning:
    def test_disable_reasoning_passes_extra_body(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="zai-glm-4.7",
            disable_reasoning=True,
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            '[{"column_name": "ssn", "category_code": "0085", '
            '"confidence": 0.9, "evidence": "SSN", "alternatives": []}]'
        )
        backend._client = mock_client

        backend.classify_batch([_make_sample()], {}, "system prompt")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["extra_body"] == {"disable_reasoning": True}

    def test_reasoning_enabled_by_default(self):
        config = LLMBackendConfig(
            backend="openai_compatible",
            base_url="http://localhost:8000/v1",
            model="zai-glm-4.7",
        )
        backend = OpenAICompatibleBackend(config)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            '[{"column_name": "ssn", "category_code": "0085", '
            '"confidence": 0.9, "evidence": "SSN", "alternatives": []}]'
        )
        backend._client = mock_client

        backend.classify_batch([_make_sample()], {}, "system prompt")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "extra_body" not in call_kwargs
