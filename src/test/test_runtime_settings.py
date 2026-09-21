"""Allowlisted runtime settings: clamp, merge, presets, generation kwargs, steps."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime.runtime_settings import (
    apply_agent_max_steps,
    apply_profile_and_provider_caps,
    apply_runtime_to_generation_kwargs,
    clamp_runtime_values,
    merge_runtime_layers,
    new_preset,
    sanitize_user_blob,
    turn_budget_overrides,
    turn_guard_overrides,
)
from src.runtime.runtime_settings_schema import (
    HARD_MAX_AGENT_STEPS,
    MAX_PRESETS_PER_USER,
)
from src.runtime.turn_budget import TurnBudget
from src.runtime.turn_compaction import (
    bump_llm_step,
    clear_turn_runtime,
    get_llm_step_count,
    set_turn_runtime,
)


def test_clamp_drops_secrets_and_extra_body():
    out = clamp_runtime_values(
        {
            "max_agent_steps": 80,
            "extra_body": {"api_key": "secret"},
            "api_key": "sk-test",
            "temperature": 0.2,
        }
    )
    assert "extra_body" not in out
    assert "api_key" not in out
    assert out["max_agent_steps"] == 80
    assert out["temperature"] == 0.2


def test_clamp_hard_caps_agent_steps(monkeypatch):
    monkeypatch.setenv("AION_MAX_AGENT_STEPS", "15")
    out = clamp_runtime_values({"max_agent_steps": 999})
    assert out["max_agent_steps"] == HARD_MAX_AGENT_STEPS


def test_merge_request_overrides_user_and_env(monkeypatch):
    monkeypatch.setenv("AION_MAX_AGENT_STEPS", "15")
    monkeypatch.setenv("AION_TEMPERATURE", "0.7")
    merged = merge_runtime_layers(
        {"max_agent_steps": 40, "temperature": 0.4},
        {"max_agent_steps": 90},
    )
    assert merged["max_agent_steps"] == 90
    assert merged["temperature"] == 0.4


def test_profile_cap_limits_user_steps():
    values = clamp_runtime_values({"max_agent_steps": 80, "max_tokens": 8192})
    capped = apply_profile_and_provider_caps(
        values,
        profile_max_agent_steps=12,
        provider_max_chat_tokens=4096,
    )
    assert capped["max_agent_steps"] == 12
    assert capped["max_tokens"] == 4096


def test_preset_limit_and_name():
    presets = [
        {"id": str(i), "name": f"p{i}", "values": {"temperature": 0.1}}
        for i in range(25)
    ]
    blob = sanitize_user_blob(
        {"values": {}, "presets": presets, "active_preset_id": "99"}
    )
    assert len(blob["presets"]) == MAX_PRESETS_PER_USER
    assert blob["active_preset_id"] is None
    with pytest.raises(ValueError):
        new_preset("  ", {"temperature": 0.5})
    p = new_preset("Deep", {"max_agent_steps": 80, "api_key": "nope"})
    assert p["name"] == "Deep"
    assert "api_key" not in p["values"]
    assert p["values"]["max_agent_steps"] == 80


def test_turn_guard_overrides_reasoning_hard_stop():
    assert turn_guard_overrides({}) == {}
    assert turn_guard_overrides({"reasoning_hard_stop": True}) == {
        "reasoning_hard_stop": True,
    }
    assert turn_guard_overrides({"reasoning_hard_stop": False}) == {
        "reasoning_hard_stop": False,
    }


def test_turn_guards_runtime_reasoning_hard_stop(monkeypatch):
    monkeypatch.setenv("AION_REASONING_HARD_STOP", "1")
    from src.runtime.turn.turn_guards import TurnGuards

    on = TurnGuards(
        message_source="user_input",
        guard_overrides={"reasoning_hard_stop": True},
    )
    off = TurnGuards(
        message_source="user_input",
        guard_overrides={"reasoning_hard_stop": False},
    )
    env_default = TurnGuards(message_source="user_input")
    assert on.reasoning_hard_stop is True
    assert off.reasoning_hard_stop is False
    assert env_default.reasoning_hard_stop is True


def test_turn_budget_overrides():
    budget = TurnBudget.load(
        overrides={"max_tool_calls": 7, "turn_timeout": 120.0, "max_tool_events": 9}
    )
    assert budget.max_tool_calls == 7
    assert budget.turn_timeout == 120.0
    assert budget.max_tool_events == 9
    mapped = turn_budget_overrides(
        {"max_tool_calls": 11, "turn_timeout_sec": 333, "max_tool_events": 4}
    )
    assert mapped["max_tool_calls"] == 11
    assert mapped["turn_timeout"] == 333
    assert mapped["max_tool_events"] == 4


def test_generation_kwargs_keeps_reasoning_effort():
    gen = {
        "reasoning_effort": "xhigh",
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
    }
    out = apply_runtime_to_generation_kwargs(
        gen,
        {"temperature": 0.2, "max_tokens": 1024, "top_k": 20, "seed": 7},
        vllm_extra=True,
    )
    assert out["reasoning_effort"] == "xhigh"
    assert out["temperature"] == 0.2
    assert out["max_tokens"] == 1024
    assert out["seed"] == 7
    assert out["extra_body"]["top_k"] == 20
    assert out["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True

    openai = apply_runtime_to_generation_kwargs(
        {"reasoning_effort": "high"},
        {"temperature": 0.1, "top_k": 40, "repetition_penalty": 1.1},
        vllm_extra=False,
    )
    assert openai["temperature"] == 0.1
    assert "extra_body" not in openai


def test_apply_agent_max_steps_restores():
    agent = SimpleNamespace(max_agent_steps=15)
    with apply_agent_max_steps(agent, 80):
        assert agent.max_agent_steps == 80
    assert agent.max_agent_steps == 15


def test_llm_step_count_does_not_double():
    agent = SimpleNamespace(max_agent_steps=50)
    set_turn_runtime(
        session_id="rt-step-test",
        loop=None,
        queue=None,
        stop_event=None,
        agent=agent,
        profile_name="aion_std",
        user_id="tester",
    )
    try:
        assert get_llm_step_count() == 0
        assert bump_llm_step("stream") == 1
        assert bump_llm_step("audit") == 1
        assert bump_llm_step("stream") == 2
        assert bump_llm_step("audit") == 2
        assert get_llm_step_count() == 2
        from src.runtime.turn_compaction import resolve_turn_runtime

        live = resolve_turn_runtime("rt-step-test")
        assert live["effective_max_agent_steps"] == 50
    finally:
        clear_turn_runtime("rt-step-test")


@pytest.mark.asyncio
async def test_resolve_turn_prefers_request_over_env(monkeypatch):
    monkeypatch.setenv("AION_MAX_AGENT_STEPS", "15")
    monkeypatch.setenv("AION_TEMPERATURE", "0.7")
    from src.runtime.runtime_settings import resolve_turn_runtime_settings

    out = await resolve_turn_runtime_settings(
        {"max_agent_steps": 80, "temperature": 0.15},
        None,
        profile_max_agent_steps=200,
    )
    assert out["max_agent_steps"] == 80
    assert out["temperature"] == 0.15
