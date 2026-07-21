"""Per-profile critical_skills for index prompt mode."""

from __future__ import annotations

import pytest

from src.agent_profile import AgentProfile, DEFAULT_CRITICAL_SKILL_NAMES


@pytest.fixture(autouse=True)
def prompt_env(monkeypatch):
    monkeypatch.setenv("AION_SKILL_SYSTEM_PROMPT_MODE", "index")
    monkeypatch.setenv("AION_SOUL_MEMORY_USER_SPLIT", "0")


def test_critical_override_only_core_loaded_full():
    p = AgentProfile(
        name="T",
        description="",
        instructions="Hi",
        skills=["core_protocol", "infra_audit"],
        critical_skills=["core_protocol"],
        slug="t",
    )
    body = p.generate_system_prompt()
    assert "### Protocol rules (core_protocol)" in body
    assert "### Protocol rules (infra_audit)" not in body
    assert "## Other available skills" in body
    assert "infra_audit" in body


def test_critical_empty_still_inlines_core_protocol():
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
    assert "### Protocol rules (infra_audit)" not in body
    assert "## Other available skills" in body


def test_critical_none_matches_legacy_default():
    assert "agent_db_protocol" in DEFAULT_CRITICAL_SKILL_NAMES
    p = AgentProfile(
        name="T",
        description="",
        instructions="Hi",
        skills=["agent_db_protocol"],
        critical_skills=None,
        slug="t",
    )
    body = p.generate_system_prompt()
    assert "### Protocol rules (agent_db_protocol)" in body


def test_datetime_placeholders_resolved_in_inlined_skills():
    """core_protocol documents {{current_date}}/{{current_time}}; must not leak to Haystack Jinja2."""
    p = AgentProfile(
        name="T",
        description="",
        instructions="Today: {{current_date}} at {{current_time}}.",
        skills=["core_protocol"],
        slug="t",
    )
    body = p.generate_system_prompt()
    assert "{{current_date}}" not in body
    assert "{{current_time}}" not in body
    assert "Today:" in body
    assert "### Protocol rules (core_protocol)" in body
