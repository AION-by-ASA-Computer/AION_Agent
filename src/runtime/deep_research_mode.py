"""Deep Research Mode: blocked tools and system prompt."""

from __future__ import annotations

import os
from typing import FrozenSet

# Tools removed from the agent in Deep Research mode: everything the model
# could use to research "by hand" (web, sandbox, plans, skills) instead of
# starting the research job, which has its own search/extraction pipeline.
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
        "complete_execution_plan",
        "delegate_to_subagent",
        "skill_view",
        "skill_search",
        "skill_list",
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
    """System-prompt section appended in Deep Research mode.

    Used by ``src.main`` (agent build) and ``refresh_agent_turn_context``
    (every turn). The research job does all planning, searching and writing
    in its own pipeline, so the agent must only start it: no clarifying
    questions, no planning and no answer from its own knowledge. The tools are
    resident in this mode (see ``src.runtime.deep_research_tools``), hence the
    explicit "already in your tool list" line, which also defuses stale
    ``tool_search`` results left in the history by earlier turns.
    """
    return (
        "\n\n## DEEP RESEARCH MODE ACTIVE\n"
        "You are in **DEEP RESEARCH MODE**. Every user request in this mode is a "
        "research request handled by the Deep Research engine, not by you.\n\n"
        "### Required flow\n"
        "1. Your **first and only action** is to call **`trigger_research`** with "
        "`topic` = the user's request, restated faithfully as one string in the "
        "user's language (keep every detail, add nothing).\n"
        "2. Do **not** plan, outline, ask clarifying questions, search, or answer "
        "from your own knowledge first: the research pipeline does planning, web "
        "search, reading and report writing on its own.\n"
        "3. After the tool returns, reply in one or two sentences that the "
        "research is running and include the markdown link it returned "
        "(`[topic](#research-<session_id>)`). Do not summarise the topic.\n"
        "4. If `trigger_research` returns an error, report the error to the user; "
        "never replace the research with your own answer.\n"
        "5. Only when the user explicitly asks about past reports, use "
        "**`manage_research`** (`action=list|read|delete`).\n\n"
        "`trigger_research` and `manage_research` are already in your tool list: "
        "call them directly, do not use `tool_search` for them, and ignore any "
        "earlier `tool_search` result in this conversation saying they were not "
        "available.\n"
    )
