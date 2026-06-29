"""In-process gate blocks skill_view before MCP when skill not on profile."""

from __future__ import annotations

from src.mcp_manager import mcp_manager
from src.runtime.skill_profile_gate import block_skills_hub_tool_if_needed


def test_block_skill_view_for_postgres_profile(monkeypatch):
    monkeypatch.setenv("AION_SKILL_VIEW_ENFORCE_PROFILE", "1")
    sid = "test-session-gate"
    mcp_manager._session_ctx[sid] = ("postgres_metadata_assistant", "u1", "default")
    try:
        msg = block_skills_hub_tool_if_needed(
            "skills_hub",
            "skill_view",
            sid,
            {"name": "db_navigation_map", "materialize": False},
        )
        assert msg is not None
        assert "is not enabled in the active profile" in msg
        for allowed in ("wren", "openmetadata_guide", "datasource_memory_protocol"):
            assert (
                block_skills_hub_tool_if_needed(
                    "skills_hub",
                    "skill_view",
                    sid,
                    {"name": allowed, "materialize": False},
                )
                is None
            )
    finally:
        mcp_manager._session_ctx.pop(sid, None)
