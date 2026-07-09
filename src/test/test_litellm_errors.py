"""Tests for LiteLLM error classification and SSE payloads."""

from __future__ import annotations

from src.runtime.litellm_errors import (
    LiteLLMErrorCode,
    classify_litellm_error,
    is_context_length_error,
    litellm_error_to_sse,
    user_message_for_code,
)


def test_context_window_from_issue_log():
    exc = RuntimeError(
        "litellm.ContextWindowExceededError: litellm.BadRequestError: "
        "This model's maximum context length is 131072 tokens. However, you requested "
        "131000 tokens in the messages and 8192 in the completion."
    )
    assert classify_litellm_error(exc) == LiteLLMErrorCode.CONTEXT_LENGTH
    assert is_context_length_error(exc)


def test_context_window_chained_cause():
    root = ValueError("maximum context length is 8192 tokens")
    wrapped = RuntimeError("agent failed")
    wrapped.__cause__ = root
    assert classify_litellm_error(wrapped) == LiteLLMErrorCode.CONTEXT_LENGTH


def test_authentication_error_by_text():
    exc = Exception("Error code: 401 - invalid api key provided")
    assert classify_litellm_error(exc) == LiteLLMErrorCode.AUTH


def test_rate_limit_error():
    exc = Exception("Rate limit exceeded (429)")
    assert classify_litellm_error(exc) == LiteLLMErrorCode.RATE_LIMIT


def test_connection_error():
    exc = ConnectionError("Connection refused")
    assert classify_litellm_error(exc) == LiteLLMErrorCode.CONNECTION


def test_model_not_found():
    exc = Exception("The model `gpt-missing` does not exist")
    assert classify_litellm_error(exc) == LiteLLMErrorCode.MODEL_NOT_FOUND


def test_litellm_error_to_sse_unified_shape():
    exc = RuntimeError("context window exceeded for model xyz")
    payload = litellm_error_to_sse(exc)
    assert payload["type"] == "llm_error"
    assert payload["code"] == LiteLLMErrorCode.CONTEXT_LENGTH
    assert payload["message"] == payload["content"]
    assert "context window" in payload["message"].lower()
    assert payload["exc_type"] == "RuntimeError"


def test_user_message_for_unknown_includes_detail():
    exc = Exception("weird provider glitch")
    msg = user_message_for_code(LiteLLMErrorCode.UNKNOWN, exc)
    assert "weird provider glitch" in msg
