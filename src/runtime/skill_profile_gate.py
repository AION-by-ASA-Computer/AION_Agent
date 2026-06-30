"""Enforce profile.skills allowlist for skills_hub (in-process + MCP)."""

from __future__ import annotations

import os
from typing import Optional


def _enforce_enabled() -> bool:
    return os.getenv("AION_SKILL_VIEW_ENFORCE_PROFILE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


_OFFICE_SLUGS = {"docx", "pdf", "xlsx", "pptx"}


def skill_allowed_for_profile_slug(skill_name: str, profile_slug: str) -> bool:
    name_strip = (skill_name or "").strip()
    if name_strip in _OFFICE_SLUGS:
        return True
    if not _enforce_enabled() or not (profile_slug or "").strip():
        return True
    try:
        from src.agent_profile import profile_manager

        profile_manager.load_all_if_stale()
        prof = profile_manager.get_profile(profile_slug.strip())
        if not prof or not prof.skills:
            return True
        return name_strip in prof.skills
    except Exception:
        return True


def skill_view_denied_message(skill_name: str, profile_slug: str) -> str:
    try:
        from src.agent_profile import profile_manager

        profile_manager.load_all_if_stale()
        prof = profile_manager.get_profile(profile_slug.strip())
        allowed = list(prof.skills) if prof and prof.skills else []
    except Exception:
        allowed = []
    return (
        f"Skill '{skill_name}' is not enabled in the active profile `{profile_slug}`. "
        f"Allowed skills: {', '.join(allowed) or '(none)'}. "
        "For DB navigation use `mempalace_search` / chat-ui project drawer, "
        "not `skill_view` on skills removed from the profile."
    )


def resolve_profile_slug_for_session(session_id: str) -> str:
    """Profile slug from MCP pool context (warm_session), else env fallback."""
    try:
        from src.mcp_manager import mcp_manager

        sctx = mcp_manager.get_session_context(session_id or "")
        if sctx:
            return (sctx.profile_slug or "").strip()
    except Exception:
        pass
    return (os.getenv("AION_CURRENT_PROFILE_SLUG") or "").strip()


def block_skills_hub_tool_if_needed(
    server_name: str,
    tool_name: str,
    session_id: str,
    arguments: dict,
) -> Optional[str]:
    """
    Return error text if the tool call must be blocked; None if allowed.
    Covers skill_view / skill_list when MCP subprocess is stale.
    """
    if (server_name or "").strip() != "skills_hub":
        return None
    base = (tool_name or "").strip()
    if base not in ("skill_view", "skill_list"):
        return None
    if not _enforce_enabled():
        return None
    slug = resolve_profile_slug_for_session(session_id)
    if not slug:
        return None
    if base == "skill_list":
        return None
    skill_name = (arguments.get("name") or arguments.get("skill") or "").strip()
    if not skill_name:
        return None
    if skill_allowed_for_profile_slug(skill_name, slug):
        return None
    return skill_view_denied_message(skill_name, slug)
