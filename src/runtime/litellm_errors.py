"""Classify LiteLLM / OpenAI-compatible provider errors for SSE and logging."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from litellm.exceptions import (
        APIConnectionError,
        APIError,
        AuthenticationError,
        BadRequestError,
        ContentPolicyViolationError,
        ContextWindowExceededError,
        InternalServerError,
        NotFoundError,
        RateLimitError,
        ServiceUnavailableError,
        Timeout,
    )

    _LITELLM_TYPES: Tuple[type, ...] = (
        ContextWindowExceededError,
        AuthenticationError,
        RateLimitError,
        APIConnectionError,
        Timeout,
        NotFoundError,
        BadRequestError,
        ContentPolicyViolationError,
        ServiceUnavailableError,
        InternalServerError,
        APIError,
    )
except ImportError:  # pragma: no cover - litellm optional in some test envs
    _LITELLM_TYPES = ()


class LiteLLMErrorCode(StrEnum):
    CONTEXT_LENGTH = "context_length_exceeded"
    AUTH = "authentication_failed"
    RATE_LIMIT = "rate_limit"
    CONNECTION = "connection_failed"
    TIMEOUT = "timeout"
    MODEL_NOT_FOUND = "model_not_found"
    BAD_REQUEST = "bad_request"
    CONTENT_POLICY = "content_policy"
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"


_USER_MESSAGES: Dict[LiteLLMErrorCode, str] = {
    LiteLLMErrorCode.CONTEXT_LENGTH: (
        "This request exceeded the model's context window. Start a new chat, "
        "shorten your message, or lower Max Chat Tokens (AION_CHAT_MAX_TOKENS) "
        "in Admin → Settings."
    ),
    LiteLLMErrorCode.AUTH: (
        "LLM authentication failed. Check the API key and provider settings "
        "in Admin → Settings."
    ),
    LiteLLMErrorCode.RATE_LIMIT: (
        "The LLM provider rate-limited this request. Wait a moment and try again."
    ),
    LiteLLMErrorCode.CONNECTION: (
        "Could not reach the LLM endpoint. Verify the base URL, network, "
        "and that the server is running."
    ),
    LiteLLMErrorCode.TIMEOUT: (
        "The LLM request timed out. Try again or increase the provider timeout."
    ),
    LiteLLMErrorCode.MODEL_NOT_FOUND: (
        "The configured model was not found on the provider. Check the model id "
        "in Admin → Settings."
    ),
    LiteLLMErrorCode.BAD_REQUEST: (
        "The LLM provider rejected the request. Check model settings and request parameters."
    ),
    LiteLLMErrorCode.CONTENT_POLICY: (
        "The LLM provider blocked this request due to a content policy violation."
    ),
    LiteLLMErrorCode.SERVER_ERROR: (
        "The LLM provider returned a server error. Try again in a few moments."
    ),
    LiteLLMErrorCode.UNKNOWN: "The LLM request failed. See server logs for details.",
}


def iter_exception_chain(exc: BaseException) -> Iterable[BaseException]:
    """Yield *exc* and linked causes/contexts without infinite loops."""
    seen: set[int] = set()
    stack: List[BaseException] = [exc]
    while stack:
        current = stack.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        yield current
        cause = current.__cause__
        if cause is not None and id(cause) not in seen:
            stack.append(cause)
        ctx = current.__context__
        if ctx is not None and ctx is not cause and id(ctx) not in seen:
            stack.append(ctx)


def _combined_error_text(exc: BaseException) -> str:
    parts: List[str] = []
    for item in iter_exception_chain(exc):
        parts.append(type(item).__name__)
        parts.append(str(item))
    return " ".join(parts).lower()


def _code_from_litellm_type(exc: BaseException) -> Optional[LiteLLMErrorCode]:
    if not _LITELLM_TYPES:
        return None
    for item in iter_exception_chain(exc):
        for litellm_type in _LITELLM_TYPES:
            if isinstance(item, litellm_type):
                name = litellm_type.__name__
                if name in ("ContextWindowExceededError",):
                    return LiteLLMErrorCode.CONTEXT_LENGTH
                if name in ("AuthenticationError",):
                    return LiteLLMErrorCode.AUTH
                if name in ("RateLimitError",):
                    return LiteLLMErrorCode.RATE_LIMIT
                if name in ("APIConnectionError",):
                    return LiteLLMErrorCode.CONNECTION
                if name in ("Timeout",):
                    return LiteLLMErrorCode.TIMEOUT
                if name in ("NotFoundError",):
                    return LiteLLMErrorCode.MODEL_NOT_FOUND
                if name in ("BadRequestError",):
                    return LiteLLMErrorCode.BAD_REQUEST
                if name in ("ContentPolicyViolationError",):
                    return LiteLLMErrorCode.CONTENT_POLICY
                if name in (
                    "ServiceUnavailableError",
                    "InternalServerError",
                    "APIError",
                ):
                    return LiteLLMErrorCode.SERVER_ERROR
    return None


_CONTEXT_PATTERNS = (
    "maximum context length",
    "context length",
    "context window",
    "contextwindowexceeded",
    "input_tokens",
    "too many tokens",
    "max_tokens",
    "prompt is too long",
    "reduce the length",
)

_AUTH_PATTERNS = (
    "authentication",
    "invalid api key",
    "incorrect api key",
    "unauthorized",
    "invalid_api_key",
    "permission denied",
    "401",
)

_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "ratelimit",
    "too many requests",
    "429",
)

_CONNECTION_PATTERNS = (
    "connection error",
    "connection refused",
    "failed to connect",
    "name or service not known",
    "network is unreachable",
    "ssl",
    "certificate",
)

_TIMEOUT_PATTERNS = ("timed out", "timeout", "deadline exceeded")

_MODEL_PATTERNS = (
    "model not found",
    "does not exist",
    "invalid model",
    "model_not_found",
    "404",
)

_CONTENT_POLICY_PATTERNS = (
    "content policy",
    "content_policy",
    "safety",
    "moderation",
    "blocked",
)

_SERVER_PATTERNS = ("internal server error", "502", "503", "504", "service unavailable")


def _text_matches(text: str, patterns: Tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def classify_litellm_error(exc: BaseException) -> LiteLLMErrorCode:
    """Map an exception (often Haystack-wrapped) to a stable error code."""
    typed = _code_from_litellm_type(exc)
    if typed is not None:
        return typed

    text = _combined_error_text(exc)
    if _text_matches(text, _CONTEXT_PATTERNS):
        return LiteLLMErrorCode.CONTEXT_LENGTH
    if _text_matches(text, _AUTH_PATTERNS):
        return LiteLLMErrorCode.AUTH
    if _text_matches(text, _RATE_LIMIT_PATTERNS):
        return LiteLLMErrorCode.RATE_LIMIT
    if _text_matches(text, _CONNECTION_PATTERNS):
        return LiteLLMErrorCode.CONNECTION
    if _text_matches(text, _TIMEOUT_PATTERNS):
        return LiteLLMErrorCode.TIMEOUT
    if _text_matches(text, _MODEL_PATTERNS):
        return LiteLLMErrorCode.MODEL_NOT_FOUND
    if _text_matches(text, _CONTENT_POLICY_PATTERNS):
        return LiteLLMErrorCode.CONTENT_POLICY
    if _text_matches(text, _SERVER_PATTERNS):
        return LiteLLMErrorCode.SERVER_ERROR
    if _text_matches(text, ("bad request", "invalid request", "400")):
        return LiteLLMErrorCode.BAD_REQUEST
    return LiteLLMErrorCode.UNKNOWN


def is_context_length_error(exc: BaseException) -> bool:
    """True when *exc* (or its cause chain) indicates a context-window overflow."""
    return classify_litellm_error(exc) == LiteLLMErrorCode.CONTEXT_LENGTH


def user_message_for_code(
    code: LiteLLMErrorCode,
    exc: Optional[BaseException] = None,
) -> str:
    base = _USER_MESSAGES.get(code, _USER_MESSAGES[LiteLLMErrorCode.UNKNOWN])
    if code != LiteLLMErrorCode.UNKNOWN or exc is None:
        return base
    detail = str(exc).strip()
    if not detail:
        return base
    detail = re.sub(r"\s+", " ", detail)
    if len(detail) > 240:
        detail = detail[:237] + "..."
    return f"{base} ({detail})"


def litellm_error_to_sse(exc: BaseException) -> Dict[str, Any]:
    """Build a unified SSE chunk for chat-ui and other clients."""
    code = classify_litellm_error(exc)
    message = user_message_for_code(code, exc)
    root = next(iter(iter_exception_chain(exc)))
    return {
        "type": "llm_error",
        "code": code,
        "message": message,
        # Backward compatibility for clients that only read `content`.
        "content": message,
        "exc_type": type(root).__name__,
    }
