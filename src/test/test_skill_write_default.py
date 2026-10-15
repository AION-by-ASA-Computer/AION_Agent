"""skill_save is off unless the operator turns the env flag on."""

from __future__ import annotations

import inspect

from mcp_servers.skills_hub.server import skill_save


def test_skill_save_default_is_off_and_category_is_generated(monkeypatch):
    monkeypatch.delenv("AION_SKILL_WRITE_ENABLED", raising=False)
    assert inspect.signature(skill_save).parameters["category"].default == "generated"
    result = skill_save(
        name="should-not-write",
        description="no",
        content="no",
    )
    assert "disabled" in result.lower()
