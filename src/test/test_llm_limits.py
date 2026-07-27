import json

import pytest

from src.runtime.llm_limits import (
    pi_runtime_config_fingerprint,
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
    assert resolve_chat_max_tokens(long_run=False) == 16384


def test_resolve_chat_max_tokens_long_run_override(monkeypatch, fresh_settings):
    monkeypatch.setenv("AION_CHAT_MAX_TOKENS", "8192")
    monkeypatch.setenv("AION_LONG_RUN_MAX_TOKENS", "24576")
    get_settings.cache_clear()
    assert resolve_chat_max_tokens(long_run=True) == 24576


def test_resolve_chat_max_tokens_long_run_falls_back_to_chat(monkeypatch, fresh_settings):
    monkeypatch.setenv("AION_CHAT_MAX_TOKENS", "16384")
    monkeypatch.delenv("AION_LONG_RUN_MAX_TOKENS", raising=False)
    get_settings.cache_clear()
    assert resolve_chat_max_tokens(long_run=True) == 16384


def test_resolve_context_window(monkeypatch, fresh_settings):
    monkeypatch.setenv("AION_CONTEXT_WINDOW", "65536")
    get_settings.cache_clear()
    assert resolve_context_window() == 65536


def test_pi_fingerprint_changes_with_max_tokens(monkeypatch, fresh_settings):
    monkeypatch.delenv("AION_LONG_RUN_MAX_TOKENS", raising=False)
    monkeypatch.setenv("AION_LONG_RUN_MAX_TOKENS", "")
    monkeypatch.setenv("AION_CHAT_MAX_TOKENS", "8192")
    get_settings.cache_clear()
    fp1 = pi_runtime_config_fingerprint()
    monkeypatch.setenv("AION_CHAT_MAX_TOKENS", "16384")
    get_settings.cache_clear()
    fp2 = pi_runtime_config_fingerprint()
    assert fp1 != fp2


@pytest.mark.asyncio
async def test_write_pi_models_json_uses_long_run_tokens(tmp_path, monkeypatch):
    from src.runtime.pi_runtime.session_config import write_pi_models_json

    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()

    class _Profile:
        name = "test"

    async def _fake_resolve(_name):
        from src.runtime.pi_runtime.session_config import PiLlmConfig

        return PiLlmConfig(
            base_url="http://127.0.0.1:8000/v1",
            model_id="test-model",
            api_key="test",
        )

    monkeypatch.setattr(
        "src.runtime.pi_runtime.session_config.resolve_pi_llm_config",
        _fake_resolve,
    )
    monkeypatch.setenv("AION_CHAT_MAX_TOKENS", "8192")
    monkeypatch.setenv("AION_LONG_RUN_MAX_TOKENS", "16384")
    get_settings.cache_clear()

    await write_pi_models_json(agent_dir, _Profile(), None)
    data = json.loads((agent_dir / "models.json").read_text(encoding="utf-8"))
    model = data["providers"]["aion"]["models"][0]
    assert model["maxTokens"] == 16384
