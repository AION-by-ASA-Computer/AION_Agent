"""Tests for deep research agent mode resolution."""

from src.runtime.agent_mode_resolve import resolve_agent_mode


def test_deep_research_mode_flag():
    assert resolve_agent_mode("normal", deep_research_mode=True) == "deep_research"


def test_deep_research_mode_off():
    assert resolve_agent_mode("deep_research", deep_research_mode=False) == "normal"


def test_internal_trigger_forces_normal():
    assert (
        resolve_agent_mode(
            "deep_research", deep_research_mode=True, message_source="internal_trigger"
        )
        == "normal"
    )
