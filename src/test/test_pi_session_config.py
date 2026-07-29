import json
from pathlib import Path

import pytest

from src.runtime.pi_runtime.session_config import (
    _is_qwen_vllm_model,
    write_pi_models_json,
)


def test_is_qwen_vllm_model():
    assert _is_qwen_vllm_model("AIONQ35-35-Q8B", "http://192.168.1.1:8000/v1")
    assert not _is_qwen_vllm_model("gpt-4o", "https://api.openai.com/v1")


@pytest.mark.asyncio
async def test_write_pi_models_json_qwen_compat(tmp_path, monkeypatch):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()

    class _Profile:
        name = "test"

    async def _fake_resolve(_name):
        from src.runtime.pi_runtime.session_config import PiLlmConfig

        return PiLlmConfig(
            base_url="http://192.168.1.1:8000/qwen3/v1",
            model_id="AIONQ35-35-Q8B",
            api_key="test",
        )

    monkeypatch.setattr(
        "src.runtime.pi_runtime.session_config.resolve_pi_llm_config",
        _fake_resolve,
    )

    await write_pi_models_json(agent_dir, _Profile(), "vllm_qwen")
    data = json.loads((agent_dir / "models.json").read_text(encoding="utf-8"))
    provider = data["providers"]["aion"]
    assert provider["compat"]["thinkingFormat"] == "qwen-chat-template"
    assert provider["compat"]["supportsStrictMode"] is False
    model = provider["models"][0]
    assert model["reasoning"] is True
    assert model["id"] == "AIONQ35-35-Q8B"


def test_pi_thinking_level_for_effort():
    from src.runtime.pi_runtime.pi_turn_runner import pi_thinking_level_for_effort

    assert pi_thinking_level_for_effort("min") == "off"
    assert pi_thinking_level_for_effort("medium") == "medium"
    assert pi_thinking_level_for_effort("max") == "high"
