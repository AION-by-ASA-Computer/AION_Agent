import pytest
import os
from haystack.utils.auth import Secret
from haystack.components.generators.chat import OpenAIChatGenerator

from src.runtime.llm_adapter import resolve_llm_endpoint
from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper


def test_resolve_llm_endpoint_requires_env(monkeypatch):
    monkeypatch.delenv("AION_API_URL", raising=False)
    monkeypatch.delenv("AION_MODEL", raising=False)
    with pytest.raises(ValueError, match="AION_API_URL"):
        resolve_llm_endpoint()


def test_resolve_llm_endpoint_ok(monkeypatch):
    monkeypatch.setenv("AION_API_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("AION_MODEL", "test-model")
    url, model = resolve_llm_endpoint()
    assert url.endswith("/v1")
    assert model == "test-model"


def test_normalize_litellm_provider_remote_vllm():
    from src.runtime.llm_adapter import normalize_litellm_provider

    assert normalize_litellm_provider("vllm", "http://localhost:8000/v1") == "openai"
    assert normalize_litellm_provider("vllm", "") == "vllm"
    assert normalize_litellm_provider("openai", "http://x/v1") == "openai"


def test_lite_llm_wrapper_remotes_vllm_provider(monkeypatch):
    monkeypatch.delenv("AION_LLM_ADAPTER", raising=False)

    wrapper = LiteLLMChatGeneratorWrapper(
        model="vllm/AIONQ35-35-Q8B",
        api_base_url="http://localhost:8000/v1",
        api_key=Secret.from_token("test-key"),
        timeout=60.0,
    )

    assert wrapper.provider == "openai"
    assert wrapper.generator.model == "openai/AIONQ35-35-Q8B"


def test_lite_llm_wrapper_basic(monkeypatch):
    monkeypatch.delenv("AION_LLM_ADAPTER", raising=False)

    wrapper = LiteLLMChatGeneratorWrapper(
        model="openai/gpt-4o",
        api_base_url="http://localhost:8000/v1",
        api_key=Secret.from_token("test-key"),
        timeout=60.0,
        generation_kwargs={"temperature": 0.5},
        tools_strict=True,
    )

    assert wrapper.provider == "openai"
    assert wrapper.model_name == "gpt-4o"
    assert wrapper.generator.model == "openai/gpt-4o"
    assert wrapper.generator.api_base_url == "http://localhost:8000/v1"
    assert wrapper.generation_kwargs == {"temperature": 0.5}


def test_lite_llm_wrapper_anthropic(monkeypatch):
    monkeypatch.delenv("AION_LLM_ADAPTER", raising=False)

    wrapper = LiteLLMChatGeneratorWrapper(
        model="anthropic/claude-3-5-sonnet",
        api_key=Secret.from_token("test-key"),
        timeout=60.0,
        generation_kwargs={"temperature": 0.7},
        tools_strict=True,
    )

    assert wrapper.provider == "anthropic"
    assert wrapper.model_name == "claude-3-5-sonnet"
    assert wrapper.generator.model == "anthropic/claude-3-5-sonnet"
    assert wrapper.generation_kwargs == {"temperature": 0.7}


def test_lite_llm_wrapper_google(monkeypatch):
    monkeypatch.setenv("AION_LLM_ADAPTER", "google")

    wrapper = LiteLLMChatGeneratorWrapper(
        model="google/gemini-2.5-flash",
        api_key=Secret.from_token("test-key"),
        generation_kwargs={"temperature": 0.2},
    )

    assert wrapper.provider == "google"
    assert wrapper.model_name == "gemini-2.5-flash"
    assert wrapper.generator.model == "google/gemini-2.5-flash"
    assert wrapper.generation_kwargs == {"temperature": 0.2}
