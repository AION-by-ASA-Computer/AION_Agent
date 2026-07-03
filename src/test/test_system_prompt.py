"""Tests for model prompt assembly."""

from src.runtime.system_prompt import (
    assemble_model_prompt_section,
    select_model_prompt,
)


def test_default_fragment_always_present():
    frags = select_model_prompt()
    assert any("Only use tools" in f for f in frags)


def test_gpt_fragment_for_gpt5():
    frags = select_model_prompt(model_id="gpt-5")
    assert any("apply_patch" in f for f in frags)


def test_assemble_section_markdown():
    section = assemble_model_prompt_section(model_id="gpt-5")
    assert "Agent behavior" in section
    assert "sandbox_apply_patch" in section
