"""Resident prompt stays small; long skills are an index, not a full inline."""

from __future__ import annotations

import os

os.environ.setdefault("AION_DEFER_TOOL_GROUPS", "1")

import src.aion_env  # noqa: F401

from src.agent_profile import profile_manager
from src.memory.context_compressor import count_tokens


def _prompt(slug: str) -> str:
    profile_manager.load_all_if_stale()
    profile = profile_manager.get_profile(slug)
    assert profile is not None
    return profile.generate_system_prompt()


def test_generic_assistant_does_not_inline_incremental_protocol():
    body = _prompt("generic_assistant")
    assert "incremental_execution_protocol" in body
    assert "When to load this skill" not in body
    assert count_tokens(body) < 8000


def test_aion_std_lists_grafana_as_a_group_not_a_schema():
    body = _prompt("aion_std")
    assert "grafana" in body
    assert "activate_tool_group" in body
    assert "input_schema" not in body
    assert count_tokens(body) < 8000
