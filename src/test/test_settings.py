import pytest
from src.settings import AionSettings, get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh(monkeypatch, **env_overrides) -> AionSettings:
    """Clear the LRU cache, apply env overrides, and return a fresh settings instance."""
    get_settings.cache_clear()
    for k, v in env_overrides.items():
        monkeypatch.setenv(k, str(v))
    s = get_settings()
    get_settings.cache_clear()
    return s


# ---------------------------------------------------------------------------
# Existing tests (kept for regression)
# ---------------------------------------------------------------------------


def test_settings_load_from_env(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("AION_API_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("AION_MODEL", "m1")
    monkeypatch.setenv("AION_MAX_AGENT_STEPS", "8")
    s = get_settings()
    assert s.api_url == "http://localhost:8000/v1"
    assert s.model == "m1"
    assert s.max_agent_steps == 8
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# New fields introduced in S6
# ---------------------------------------------------------------------------


def test_stm_max_turns_default(monkeypatch):
    monkeypatch.delenv("AION_STM_MAX_TURNS", raising=False)
    s = _fresh(monkeypatch)
    assert s.stm_max_turns == 10


def test_stm_max_turns_override(monkeypatch):
    s = _fresh(monkeypatch, AION_STM_MAX_TURNS="20")
    assert s.stm_max_turns == 20


def test_stm_token_budget_none_by_default(monkeypatch):
    monkeypatch.delenv("AION_STM_TOKEN_BUDGET", raising=False)
    s = _fresh(monkeypatch)
    assert s.stm_token_budget is None


def test_stm_token_budget_set(monkeypatch):
    s = _fresh(monkeypatch, AION_STM_TOKEN_BUDGET="4096")
    assert s.stm_token_budget == 4096


def test_context_compress_enabled_default(monkeypatch):
    monkeypatch.delenv("AION_CONTEXT_COMPRESS_ENABLED", raising=False)
    s = _fresh(monkeypatch)
    assert s.context_compress_enabled is True


def test_context_compress_enabled_false(monkeypatch):
    s = _fresh(monkeypatch, AION_CONTEXT_COMPRESS_ENABLED="false")
    assert s.context_compress_enabled is False


def test_artifact_strategy_default(monkeypatch):
    # Explicitly set to the documented default so the live .env doesn't interfere.
    s = _fresh(monkeypatch, AION_ARTIFACT_STRATEGY="tool")
    assert s.artifact_strategy == "tool"


def test_artifact_strategy_override(monkeypatch):
    s = _fresh(monkeypatch, AION_ARTIFACT_STRATEGY="markdown")
    assert s.artifact_strategy == "markdown"


def test_stream_loop_v2_default(monkeypatch):
    monkeypatch.delenv("AION_STREAM_LOOP_V2", raising=False)
    s = _fresh(monkeypatch)
    assert s.stream_loop_v2 is False


def test_otel_enabled_default(monkeypatch):
    monkeypatch.delenv("AION_OTEL_ENABLED", raising=False)
    s = _fresh(monkeypatch)
    assert s.otel_enabled is False


def test_otel_enabled_true(monkeypatch):
    s = _fresh(monkeypatch, AION_OTEL_ENABLED="1")
    assert s.otel_enabled is True


def test_web_search_require_client_opt_in_default(monkeypatch):
    monkeypatch.delenv("AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN", raising=False)
    s = _fresh(monkeypatch)
    assert s.web_search_require_client_opt_in is False


def test_web_search_require_client_opt_in_set(monkeypatch):
    s = _fresh(monkeypatch, AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN="1")
    assert s.web_search_require_client_opt_in is True


def test_chat_max_tokens_default(monkeypatch):
    # Explicitly pin to the documented default to isolate from live .env.
    s = _fresh(monkeypatch, AION_CHAT_MAX_TOKENS="8192")
    assert s.chat_max_tokens == 8192


def test_chat_max_tokens_override(monkeypatch):
    s = _fresh(monkeypatch, AION_CHAT_MAX_TOKENS="16384")
    assert s.chat_max_tokens == 16384


def test_default_reasoning_effort_default(monkeypatch):
    # Explicitly set to empty string (the documented default).
    s = _fresh(monkeypatch, AION_DEFAULT_REASONING_EFFORT="")
    assert s.default_reasoning_effort == ""


def test_default_reasoning_effort_set(monkeypatch):
    s = _fresh(monkeypatch, AION_DEFAULT_REASONING_EFFORT="medium")
    assert s.default_reasoning_effort == "medium"


def test_plan_mode_tool_first_present(monkeypatch):
    monkeypatch.delenv("AION_PLAN_MODE_TOOL_FIRST", raising=False)
    s = _fresh(monkeypatch)
    assert s.plan_mode_tool_first is True


def test_plan_text_parser_present(monkeypatch):
    monkeypatch.delenv("AION_PLAN_TEXT_PARSER", raising=False)
    s = _fresh(monkeypatch)
    assert s.plan_text_parser is False


# ---------------------------------------------------------------------------
# validate_settings_at_startup integration test (no API server needed)
# ---------------------------------------------------------------------------


def test_validate_settings_at_startup_no_api_url(monkeypatch, caplog):
    """validate_settings_at_startup should log an error but NOT raise when api_url is empty."""
    import logging

    # Use setenv("", ...) rather than delenv so os.environ overrides the live .env file.
    monkeypatch.setenv("AION_API_URL", "")
    get_settings.cache_clear()
    from src.api.main import validate_settings_at_startup

    with caplog.at_level(logging.ERROR, logger="aion.api"):
        # Must not raise
        validate_settings_at_startup()

    get_settings.cache_clear()
    assert any("AION_API_URL" in r.message for r in caplog.records), (
        "Expected an error log mentioning AION_API_URL"
    )


def test_validate_settings_at_startup_valid(monkeypatch, caplog):
    """When api_url is set, validate_settings_at_startup should not emit error logs."""
    import logging

    get_settings.cache_clear()
    monkeypatch.setenv("AION_API_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("AION_MODEL", "test-model")
    from src.api.main import validate_settings_at_startup

    with caplog.at_level(logging.ERROR, logger="aion.api"):
        validate_settings_at_startup()

    get_settings.cache_clear()
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not error_records, f"Unexpected error logs: {error_records}"
