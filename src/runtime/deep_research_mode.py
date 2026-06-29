"""Deep Research Mode: blocked tools and system prompt."""
from __future__ import annotations

import os
from typing import FrozenSet

DEFAULT_DEEP_RESEARCH_BLOCKED_TOOLS: FrozenSet[str] = frozenset(
    {
        "sandbox_write_workspace_file",
        "sandbox_edit_workspace_file",
        "sandbox_exec_allowlisted",
        "sandbox_run_python_file",
        "sandbox_install_python_packages",
        "sandbox_install_npm_packages",
        "sandbox_run_node_file",
        "draft_execution_plan",
        "get_execution_plan",
        "update_execution_plan",
        "mark_task_completed",
        "delegate_to_subagent",
        "skill_view",
        "web_search",
        "web_fetch_page",
    }
)


def deep_research_blocked_tool_names() -> set[str]:
    raw = (os.getenv("AION_DEEP_RESEARCH_BLOCKED_TOOLS") or "").strip()
    if raw:
        return {t.strip() for t in raw.split(",") if t.strip()}
    return set(DEFAULT_DEEP_RESEARCH_BLOCKED_TOOLS)


def build_deep_research_system_prompt() -> str:
    return (
        "\n\n## DEEP RESEARCH MODE ACTIVE\n"
        "You are in **DEEP RESEARCH MODE**. The user wants a thorough, multi-source "
        "research report — not a quick chat answer.\n\n"
        "### Required flow\n"
        "1. Clarify scope only if the request is ambiguous (max 2 questions).\n"
        "2. Call **`trigger_research`** with a focused `topic` string capturing the full intent.\n"
        "3. Tell the user the job is running and include the markdown link returned by the tool "
        "(`[topic](#research-<session_id>)`).\n"
        "4. Do **not** run manual `web_search` loops — the research engine handles search, "
        "extraction, and synthesis.\n"
        "5. To open past reports use **`manage_research`** (`action=list|read|delete`).\n\n"
        "### Tool disambiguation\n"
        "- `web_search` = single quick lookup (blocked in this mode)\n"
        "- `trigger_research` = full iterative report with HTML export\n"
    )
