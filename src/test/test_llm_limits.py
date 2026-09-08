import pytest

from src.runtime.llm_limits import (
    resolve_chat_max_tokens,
    resolve_context_window,
)
from src.settings import get_settings


@pytest.fixture
def fresh_settings(monkeypatch):
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_resolve_chat_max_tokens_uses_settings(monkeypatch, fresh_settings):
    monkeypatch.setenv("AION_CHAT_MAX_TOKENS", "16384")
    get_settings.cache_clear()
    assert resolve_chat_max_tokens() == 16384


def test_resolve_context_window(monkeypatch, fresh_settings):
    monkeypatch.setenv("AION_CONTEXT_WINDOW", "65536")
    get_settings.cache_clear()
    assert resolve_context_window() == 65536
