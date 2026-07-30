"""Skill package loading — optional proprietary pptx skill."""

from __future__ import annotations

import pytest

from src.skill_registry import SkillRegistry


def test_pptx_skill_anthropic_aligned_body():
    reg = SkillRegistry()
    reg.reload()
    body = reg.get_skill_full("pptx")
    if not body:
        pytest.skip(
            "pptx skill not installed — populate config_proprietary/skills/pptx "
            "and run scripts/sync_proprietary_config.py"
        )
    assert "Creating with pptxgenjs" in body
    assert "scripts/office/validate.py" in body
    assert "AION sandbox" in body
    assert "NEVER pres.createSlide" in body or "NEVER pres.layout()" in body
    assert "Package reference:" not in body


def test_non_package_skill_has_no_companion_suffix():
    reg = SkillRegistry()
    reg.reload()
    body = reg.get_skill_full("artifact_protocol")
    assert body
    assert "Package reference:" not in body
