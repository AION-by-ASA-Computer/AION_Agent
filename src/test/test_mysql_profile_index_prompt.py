"""MySQL metadata profile uses index mode + critical_skills (not full skill dump)."""

from __future__ import annotations

import os

import pytest

from src.agent_profile import profile_manager


@pytest.fixture(autouse=True)
def prompt_env(monkeypatch):
    monkeypatch.setenv("AION_SKILL_SYSTEM_PROMPT_MODE", "index")
    monkeypatch.setenv("AION_SOUL_MEMORY_USER_SPLIT", "0")
    monkeypatch.setenv("AION_ARTIFACT_STRATEGY", "markdown")


def test_mysql_profile_critical_only_full_bodies():
    profile_manager.load_all()
    p = profile_manager.get_profile("mysql_metadata_assistant")
    assert p is not None
    assert p.critical_skills is not None
    assert "openmetadata_guide" not in p.critical_skills
    assert "charts_generation" not in p.critical_skills

    body = p.generate_system_prompt()
    assert "### Protocol rules (core_protocol)" in body
    assert "### Protocol rules (datasource_memory_protocol)" in body
    assert "## Other available skills" in body
    assert "`openmetadata_guide`" in body
    assert "`charts_generation`" in body
    # Full OM guide body should not be inlined in index mode
    assert body.count("# OpenMetadata (OM) Integration") == 0
    assert body.count("# Interactive Dynamic Charts") == 0
    assert len(body) < 24_000
