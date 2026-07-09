"""Soft nudge: remind the agent to load skills before specialized work."""

from __future__ import annotations

import re
from typing import Optional

_DOC_OFFICE = re.compile(
    r"\b(docx|doc\b|word|pdf|xlsx|excel|pptx|powerpoint|\.docx|documento|corso|manuale|bibliografia)\b",
    re.I,
)
_CODE_WRITE = re.compile(
    r"\b(sandbox_write|scrivi\s+file|crea\s+file|genera\s+documento|ultra\s+dettagliat)\b",
    re.I,
)


def should_inject_skill_discovery_nudge(
    user_message: str,
    *,
    profile_has_skills_hub: bool,
    agent_mode: str = "normal",
    session_id: Optional[str] = None,
) -> bool:
    if (agent_mode or "normal").strip().lower() == "plan":
        return False
    if not profile_has_skills_hub:
        return False
    return True


def build_skill_discovery_nudge(
    user_message: str,
    session_id: Optional[str] = None,
    profile_skills: Optional[list[str]] = None,
    critical_skills: Optional[set[str] | frozenset[str]] = None,
) -> str:
    del user_message  # nudge is generic; profile skills vary

    loaded_skills = []
    if session_id:
        try:
            from src.session_workspace import session_root

            assets_dir = session_root(session_id) / ".aion_skill_assets"
            if assets_dir.is_dir():
                loaded_skills = sorted(
                    [f.stem for f in assets_dir.glob("*.json") if f.is_file()]
                )
        except Exception:
            pass

    loaded_info = ""
    if loaded_skills:
        loaded_info = f"Skills already loaded in this conversation so far: {', '.join(loaded_skills)}.\n"

    # Determina le skill del profilo, escludendo quelle critiche (inlined)
    if critical_skills is None:
        try:
            from src.agent_profile import DEFAULT_CRITICAL_SKILL_NAMES

            ignored_skills = set(DEFAULT_CRITICAL_SKILL_NAMES)
        except ImportError:
            ignored_skills = {"core_protocol", "artifact_protocol", "agent_db_protocol"}
    else:
        ignored_skills = set(critical_skills)

    avail = [s for s in (profile_skills or []) if s not in ignored_skills]
    not_loaded = [s for s in avail if s not in loaded_skills]

    if avail:
        avail_str = ", ".join(avail)
        example_str = (
            f"like {avail[0]} or other available skills"
            if len(avail) > 0
            else "available skills"
        )
        list_desc = f"the specific skill you need from the profile's available list ({avail_str})"
    else:
        example_str = (
            "reading or creating PDF/Word/Excel documents, operating on Plane, etc."
        )
        list_desc = "the specific skill you need (e.g. pdf, docx, xlsx, plane, etc.)"

    if avail and not not_loaded:
        return (
            "[System instruction — skill discovery]\n"
            "All available profile skills are already loaded.\n"
            f"{loaded_info}"
            "Use their tools and rules directly. Do not call `skill_view` again.\n\n"
        )

    missing_info = ""
    if not_loaded:
        missing_info = f"Available skills NOT yet loaded: {', '.join(not_loaded)}.\n"

    return (
        "[System instruction — skill discovery]\n"
        f"Before performing any specialized operations ({example_str}) or writing files/code in the workspace for this task:\n"
        f"{loaded_info}"
        f"{missing_info}"
        f"1. **CHECK LOADED SKILLS:** Look at the 'Skills already loaded' list above. If the specific skill you need is already listed, do not call `skill_view` for it again, do not announce that you are loading it, and use its tools directly.\n"
        f'2. **LOAD MISSING SKILLS:** If the skill you need is in the available list ({avail_str if avail else "profile skills"}) but NOT loaded, you MUST load the correct skill first by calling `skill_view(name="skill_name")`.\n'
        "3. **LOAD MULTIPLE SKILLS IF NEEDED:** If a task requires multiple skills, you can load all of them in the same turn by calling `skill_view` for each required skill.\n"
        "4. **PROFILE LIMITATIONS & FALLBACK:** If a skill you need is not enabled/available in the current profile (i.e. `skill_view` returns an error or is blocked), explain this to the user and complete the task using standard available tools (e.g. OCR or direct file reads).\n"
        "Only after loading any required missing skills, proceed to execute the task.\n\n"
    )


def build_plan_mode_skill_hint(user_message: str) -> str:
    """Prepended in Plan Mode — Cursor-style: plan first, defer skill_view/web research to tasks."""
    from src.runtime.plan_mode import plan_mode_max_research_tools

    budget = plan_mode_max_research_tools()
    deliverable = "deliverable"
    if _DOC_OFFICE.search(user_message or ""):
        deliverable = "requested document/course"
    return (
        "[Plan Mode — Cursor flow]\n"
        f"The user asked for a complex {deliverable}. In **this** turn:\n"
        f"1. At most **{budget}** read-only tools (e.g. list workspace) if strictly needed.\n"
        "2. **Do not** call `skill_view` (blocked) or a series of thematic `web_search`.\n"
        "3. Output = **only** `<plan>...</plan>` for the sidebar, then STOP.\n"
        "4. In the plan: tasks for `skill_view` (relevant skills), web research, chapters, bibliography **after** Approve Plan.\n"
        "5. `## Goal` = **current** request; do not reuse old forecasting/commercial templates.\n\n"
    )
