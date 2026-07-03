"""Tests for LLM connection probe and model discovery."""

from __future__ import annotations

import pytest

from src.runtime.llm_probe import (
    catalog_to_openai_models,
    infer_litellm_provider,
    probe_llm_connection,
    resolve_probe_base_url,
    should_use_catalog_fallback,
)


def test_resolve_probe_base_url_defaults():
    assert resolve_probe_base_url("openai", None).endswith("/v1")
    assert resolve_probe_base_url("ollama", None) == "http://localhost:11434/v1"
    assert resolve_probe_base_url("vllm", None) == ""


def test_resolve_probe_base_url_explicit():
    assert (
        resolve_probe_base_url("vllm", "http://192.168.1.10:8000/qwen3/v1")
        == "http://192.168.1.10:8000/qwen3/v1"
    )


def test_infer_litellm_provider_vllm_remote():
    assert (
        infer_litellm_provider("vllm", "http://localhost:8000/v1") == "openai"
    )


def test_should_use_catalog_fallback_self_hosted():
    assert should_use_catalog_fallback("vllm", "http://localhost:8000/v1") is False
    assert should_use_catalog_fallback("openai", "https://api.openai.com/v1") is True


def test_catalog_to_openai_models_shape():
    payload = catalog_to_openai_models(["gpt-4o", "gpt-4o-mini"])
    assert payload["object"] == "list"
    assert [m["id"] for m in payload["data"]] == ["gpt-4o", "gpt-4o-mini"]


@pytest.mark.asyncio
async def test_probe_llm_connection_live_models(monkeypatch):
    from src.runtime import llm_probe

    async def fake_fetch(base_url, api_key, timeout=10.0):
        assert base_url.endswith("/v1")
        return ["AIONQ35-35-Q8B", "other-model"]

    monkeypatch.setattr(llm_probe, "_fetch_live_model_ids", fake_fetch)

    result = await probe_llm_connection(
        provider="vllm",
        api_base_url="http://localhost:8000/v1",
        api_key="test-key",
    )
    assert result["healthy"] is True
    assert result["models_source"] == "live"
    ids = [m["id"] for m in result["models"]["data"]]
    assert "AIONQ35-35-Q8B" in ids
    assert result["models"]["hints"]["AIONQ35-35-Q8B"]["context_window"] > 0


@pytest.mark.asyncio
async def test_probe_llm_connection_unreachable(monkeypatch):
    from src.runtime import llm_probe

    async def fake_fetch(*_a, **_k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(llm_probe, "_fetch_live_model_ids", fake_fetch)
    monkeypatch.setattr(llm_probe, "should_use_catalog_fallback", lambda *_: False)

    with pytest.raises(ValueError, match="unreachable"):
        await probe_llm_connection(
            provider="vllm",
            api_base_url="http://localhost:8000/v1",
            api_key="x",
        )
