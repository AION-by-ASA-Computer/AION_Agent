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
) -> bool:
    if (agent_mode or "normal").strip().lower() == "plan":
        return False
    if not profile_has_skills_hub:
        return False
    text = (user_message or "").strip()
    if not text:
        return False
    return bool(_DOC_OFFICE.search(text) or _CODE_WRITE.search(text))


def build_skill_discovery_nudge(user_message: str) -> str:
    hint = "docx"
    if re.search(r"\bpdf\b", user_message, re.I):
        hint = "pdf"
    elif re.search(r"\bxlsx|excel\b", user_message, re.I):
        hint = "xlsx"
    elif re.search(r"\bpptx|powerpoint\b", user_message, re.I):
        hint = "pptx"
    return (
        "[System instruction — skill discovery]\n"
        "Before writing code or files in the workspace for this task, you must use skills_hub: "
        f"`skill_search` with a relevant query, then `skill_view` for the skill (e.g. `{hint}` or related).\n"
        "If `skill_search` finds nothing but the profile lists the skill, call "
        f"`skill_view(\"{hint}\")`.\n"
        "After `skill_view`, skill scripts (e.g. `scripts/office/unpack.py`) are in the session; "
        "use `sandbox_exec_allowlisted` with paths relative to the session root.\n"
        "Only after loading the skill proceed with mutating tools or artifacts.\n\n"
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
        "4. In the plan: tasks for `skill_view(docx)`, web research, chapters, bibliography **after** Approve Plan.\n"
        "5. `## Goal` = **current** request; do not reuse old forecasting/commercial templates.\n\n"
    )
