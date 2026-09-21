"""Native reasoning_effort mapping (UI min/medium/max → engine fields)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime.reasoning_effort import (
    detect_reasoning_dialect,
    generation_kwargs_for_agent,
    map_native_reasoning_effort,
    merge_generation_kwargs,
    native_reasoning_scale,
    resolve_turn_reasoning,
)


@pytest.fixture(autouse=True)
def _clear_reasoning_env(monkeypatch):
    for key in (
        "AION_THINKING_TOKEN_BUDGET",
        "AION_THINKING_TOKEN_BUDGET_MIN",
        "AION_THINKING_TOKEN_BUDGET_MEDIUM",
        "AION_THINKING_TOKEN_BUDGET_MAX",
        "AION_REASONING_EFFORT_MAX_BUDGET",
        "AION_NATIVE_REASONING_EFFORT_VALUES",
        "AION_NATIVE_REASONING_DIALECT",
        "AION_LLM_ADAPTER",
        "AION_MODEL",
        "OPENAI_MODEL",
        "AION_DEFAULT_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def _agent(model: str, provider: str = "openai", **gen_kw):
    gen = SimpleNamespace(provider=provider, model=model, generation_kwargs=gen_kw)
    return SimpleNamespace(chat_generator=gen)


def test_qwen38_not_confused_with_qwen3_8b():
    assert detect_reasoning_dialect("Qwen/Qwen3.8-Flash-Next") == "qwen38"
    assert detect_reasoning_dialect("openai/Qwen/Qwen3.8-27B") == "qwen38"
    assert detect_reasoning_dialect("qwen3.8-flash-next") == "qwen38"
    assert detect_reasoning_dialect("Qwen/Qwen3-8B") == "vllm"
    assert detect_reasoning_dialect("AIONQ35-35-Q8B") == "vllm"
    assert detect_reasoning_dialect("o3-mini", "openai") == "openai_reasoning"
    assert detect_reasoning_dialect("openai/o3-mini", "openai") == "openai_reasoning"


def test_qwen38_max_maps_to_xhigh_everywhere():
    merged = merge_generation_kwargs(
        {"max_tokens": 8192},
        "max",
        model="Qwen/Qwen3.8-Flash-Next",
        provider="openai",
    )
    assert merged["max_tokens"] == 8192
    assert merged["reasoning_effort"] == "xhigh"
    eb = merged["extra_body"]
    assert eb["reasoning_effort"] == "xhigh"
    assert eb["enable_thinking"] is True
    assert eb["preserve_thinking"] is True
    assert "thinking_token_budget" not in eb
    ctk = eb["chat_template_kwargs"]
    assert ctk["reasoning_effort"] == "xhigh"
    assert ctk["enable_thinking"] is True
    assert ctk["preserve_thinking"] is True
    assert "reasoning_effort" in (merged.get("allowed_openai_params") or [])


def test_qwen38_medium_maps_to_medium_without_token_budget():
    merged = merge_generation_kwargs({}, "medium", model="Qwen/Qwen3.8-27B")
    assert merged["reasoning_effort"] == "medium"
    assert merged["extra_body"]["chat_template_kwargs"]["reasoning_effort"] == "medium"
    assert "thinking_token_budget" not in merged["extra_body"]


def test_qwen38_off_disables_thinking_and_omits_native_effort():
    merged = merge_generation_kwargs(
        {
            "extra_body": {
                "thinking_token_budget": 999,
                "reasoning_effort": "xhigh",
                "chat_template_kwargs": {"reasoning_effort": "xhigh"},
            }
        },
        "off",
        model="Qwen/Qwen3.8-Flash-Next",
    )
    assert "reasoning_effort" not in merged
    eb = merged["extra_body"]
    assert "reasoning_effort" not in eb
    assert "thinking_token_budget" not in eb
    assert eb["enable_thinking"] is False
    assert eb["preserve_thinking"] is False
    ctk = eb["chat_template_kwargs"]
    assert ctk["enable_thinking"] is False
    assert "reasoning_effort" not in ctk


def test_qwen38_min_is_native_low():
    merged = merge_generation_kwargs({}, "min", model="Qwen/Qwen3.8-Flash-Next")
    assert merged["reasoning_effort"] == "low"
    ctk = merged["extra_body"]["chat_template_kwargs"]
    assert ctk["enable_thinking"] is True
    assert ctk["reasoning_effort"] == "low"


def test_qwen38_never_emits_high():
    for ui in ("off", "min", "medium", "max"):
        native = map_native_reasoning_effort(ui, "qwen38")
        assert native != "high"
        assert native != "none"


def test_vllm_generic_max_uses_xhigh_not_high():
    """Custom served-model-name (AIONQ35-…) must not emit high: vLLM rejects it."""
    assert map_native_reasoning_effort("max", "vllm") == "xhigh"
    for model in ("Qwen/Qwen3-8B", "AIONQ35-35-Q8B", "local-custom-alias"):
        merged = merge_generation_kwargs({}, "max", model=model)
        assert merged["reasoning_effort"] == "xhigh"
        assert (
            merged["extra_body"]["chat_template_kwargs"]["reasoning_effort"] == "xhigh"
        )


def test_compat_off_omits_native_effort():
    """Omit none/high so unknown or Qwen3.8 aliases do not 500 the chat template."""
    merged = merge_generation_kwargs({}, "off", model="Qwen/Qwen3-8B")
    assert map_native_reasoning_effort("off", "vllm") is None
    assert "reasoning_effort" not in merged
    assert merged["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert "reasoning_effort" not in merged["extra_body"]["chat_template_kwargs"]


def test_compat_min_is_native_low():
    merged = merge_generation_kwargs({}, "min", model="Qwen/Qwen3-8B")
    assert merged["reasoning_effort"] == "low"
    assert merged["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert merged["extra_body"]["chat_template_kwargs"]["reasoning_effort"] == "low"


def test_resolve_turn_reasoning_toggle():
    assert resolve_turn_reasoning("min", thinking_enabled=True) == "min"
    assert resolve_turn_reasoning("min", thinking_enabled=False) == "off"
    assert resolve_turn_reasoning("max", thinking_enabled=False) == "off"
    assert resolve_turn_reasoning("min", thinking_enabled=None) == "off"
    assert resolve_turn_reasoning("medium", thinking_enabled=None) == "medium"


def test_unknown_model_still_gets_native_effort():
    med = merge_generation_kwargs({}, "medium", model="AIONQ35-35-Q8B")
    mx = merge_generation_kwargs({}, "max", model="local-custom-alias")
    for payload in (med, mx):
        assert payload["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
        assert payload["extra_body"]["chat_template_kwargs"]["reasoning_effort"]
        assert "reasoning_effort" in (payload.get("allowed_openai_params") or [])
    assert med["reasoning_effort"] == "medium"
    assert mx["reasoning_effort"] == "xhigh"


def test_empty_model_is_compat_not_forced_qwen38():
    assert detect_reasoning_dialect("") == "vllm"
    assert detect_reasoning_dialect(None) == "vllm"
    merged = merge_generation_kwargs({}, "max")
    assert merged["reasoning_effort"] == "xhigh"


def test_anthropic_medium_enables_thinking_without_preconfig():
    agent = _agent("claude-sonnet-4", provider="anthropic")
    kw = generation_kwargs_for_agent(agent, "medium")
    assert kw["thinking"]["type"] == "enabled"
    assert kw["thinking"]["budget_tokens"] > 0


def test_openai_o3_uses_top_level_only():
    kw = generation_kwargs_for_agent(
        _agent(
            "openai/o3-mini",
            extra_body={"chat_template_kwargs": {"enable_thinking": True}},
        ),
        "max",
    )
    assert kw["reasoning_effort"] == "high"
    assert "extra_body" not in kw


def test_openai_o3_min_is_low_not_off():
    kw = generation_kwargs_for_agent(_agent("o3-mini"), "min")
    assert kw["reasoning_effort"] == "low"


def test_gpt5_off_is_none_min_is_low():
    assert native_reasoning_scale("openai_reasoning", model="gpt-5.4")[0] == "none"
    kw_off = generation_kwargs_for_agent(_agent("openai/gpt-5.4"), "off")
    assert kw_off["reasoning_effort"] == "none"
    kw_min = generation_kwargs_for_agent(_agent("openai/gpt-5.4"), "min")
    assert kw_min["reasoning_effort"] == "low"
    kw_max = generation_kwargs_for_agent(_agent("openai/gpt-5.4"), "max")
    assert kw_max["reasoning_effort"] == "xhigh"


def test_generation_kwargs_preserves_max_tokens_for_qwen38():
    kw = generation_kwargs_for_agent(
        _agent("Qwen/Qwen3.8-Flash-Next", max_tokens=16384),
        "max",
    )
    assert kw["max_tokens"] == 16384
    assert kw["reasoning_effort"] == "xhigh"
    assert kw["extra_body"]["chat_template_kwargs"]["reasoning_effort"] == "xhigh"


def test_env_native_values_override(monkeypatch):
    monkeypatch.setenv("AION_NATIVE_REASONING_EFFORT_VALUES", "low,medium,max")
    monkeypatch.delenv("AION_NATIVE_REASONING_DIALECT", raising=False)
    merged = merge_generation_kwargs({}, "max", model="Qwen/Qwen3.8-Flash-Next")
    assert merged["reasoning_effort"] == "max"
    assert merged["extra_body"]["chat_template_kwargs"]["reasoning_effort"] == "max"


def test_env_thinking_budget_still_optional(monkeypatch):
    monkeypatch.setenv("AION_THINKING_TOKEN_BUDGET_MEDIUM", "500")
    monkeypatch.delenv("AION_THINKING_TOKEN_BUDGET", raising=False)
    merged = merge_generation_kwargs({}, "medium", model="Qwen/Qwen3.8-Flash-Next")
    assert merged["extra_body"]["thinking_token_budget"] == 500
    assert merged["reasoning_effort"] == "medium"


def test_max_budget_env_does_not_apply_to_medium(monkeypatch):
    monkeypatch.delenv("AION_THINKING_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("AION_THINKING_TOKEN_BUDGET_MEDIUM", raising=False)
    monkeypatch.setenv("AION_REASONING_EFFORT_MAX_BUDGET", "777")
    med = merge_generation_kwargs({}, "medium", model="Qwen/Qwen3.8-Flash-Next")
    mx = merge_generation_kwargs({}, "max", model="Qwen/Qwen3.8-Flash-Next")
    assert "thinking_token_budget" not in med["extra_body"]
    assert mx["extra_body"]["thinking_token_budget"] == 777


def test_runtime_sampling_does_not_drop_reasoning_effort():
    from src.runtime.runtime_settings import apply_runtime_to_generation_kwargs

    agent = _agent("Qwen/Qwen3.8-Flash-Next", max_tokens=2048)
    kw = generation_kwargs_for_agent(agent, "max")
    merged = apply_runtime_to_generation_kwargs(
        kw,
        {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9},
        vllm_extra=True,
    )
    assert merged["reasoning_effort"] == "xhigh"
    assert merged["temperature"] == 0.3
    assert merged["max_tokens"] == 1024
    assert merged["top_p"] == 0.9
