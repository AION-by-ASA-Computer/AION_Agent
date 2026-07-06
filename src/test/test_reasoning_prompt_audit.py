"""Regression tests for reasoning prompt audit (core_protocol, STM, generation kwargs)."""

from __future__ import annotations

import pytest

from src.agent_profile import AgentProfile
from src.data.history_bridge import UnifiedHistoryBridge
from src.runtime.reasoning_effort import merge_generation_kwargs


@pytest.fixture(autouse=True)
def prompt_env(monkeypatch):
    monkeypatch.setenv("AION_SKILL_SYSTEM_PROMPT_MODE", "index")
    monkeypatch.setenv("AION_SOUL_MEMORY_USER_SPLIT", "0")


def test_core_protocol_always_inlined_even_when_critical_skills_empty():
    p = AgentProfile(
        name="T",
        description="",
        instructions="Hi",
        skills=["infra_audit"],
        critical_skills=[],
        slug="t",
    )
    body = p.generate_system_prompt()
    assert "### Protocol rules (core_protocol)" in body


def test_stm_window_omits_reasoning_meta():
    bridge = UnifiedHistoryBridge(tenant_id="default")
    msg = bridge._row_to_chat_message(
        "assistant",
        "answer text",
        None,
        reasoning="long internal thinking that should not replay",
    )
    assert msg is not None
    assert msg.meta.get("reasoning") is None


def test_merge_generation_kwargs_medium_sets_thinking_budget():
    merged = merge_generation_kwargs({}, "medium")
    eb = merged.get("extra_body") or {}
    assert eb.get("chat_template_kwargs", {}).get("enable_thinking") is True
    assert int(eb.get("thinking_token_budget", 0)) > 0


def test_merge_generation_kwargs_min_disables_thinking():
    merged = merge_generation_kwargs(
        {"extra_body": {"thinking_token_budget": 999}}, "min"
    )
    eb = merged.get("extra_body") or {}
    assert eb.get("chat_template_kwargs", {}).get("enable_thinking") is False
    assert "thinking_token_budget" not in eb


def test_mysql_metadata_prompt_no_duplicate_datasource_overlay():
    from src.agent_profile import profile_manager

    profile_manager.load_all()
    p = profile_manager.get_profile("mysql_metadata_assistant")
    assert p is not None
    body = p.generate_system_prompt()
    assert "### Protocol rules (datasource_memory_protocol)" in body
    assert body.count("DATASOURCE MEMORY WORKFLOW (mandatory)") == 0


def test_turn_state_reminder_cache_hit():
    from src.runtime.datasource_turn_reminders import build_turn_state_reminder

    text = build_turn_state_reminder(
        cache_hit=True,
        has_sql_inject=True,
        needs_persist=False,
        user_input="count users last week",
    )
    assert text is not None
    assert "<system-reminder>" in text
    assert "cache hit" in text.lower()
