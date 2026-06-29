"""Plan Mode: blocked tools, research budget, and Cursor-aligned system prompt."""
from __future__ import annotations

import os
from typing import FrozenSet

# Mutating + plan-turn research tools removed when AION_PLAN_MODE_BLOCKED_TOOLS is unset.
DEFAULT_PLAN_MODE_BLOCKED_TOOLS: FrozenSet[str] = frozenset(
    {
        "sandbox_write_workspace_file",
        "sandbox_edit_workspace_file",
        "sandbox_exec_allowlisted",
        "sandbox_run_python_file",
        "sandbox_install_python_packages",
        "sandbox_install_npm_packages",
        "sandbox_run_node_file",
        "mark_task_completed",
        "delegate_to_subagent",
        # Full skill bodies are large; load them in post-approval tasks only.
        "skill_view",
    }
)

# Read-only tools counted toward the per-turn research budget (see build_plan_mode_system_prompt).
# Override via AION_PLAN_MODE_RESEARCH_TOOLS (comma-separated) when extra search integrations are installed.
DEFAULT_PLAN_MODE_RESEARCH_TOOLS: FrozenSet[str] = frozenset(
    {
        "list_dir",
        "sandbox_list_files",
        "view_file",
        "sandbox_read_text_file",
        "grep_search",
        "web_search",
        "web_fetch_page",
        "skill_search",
        "skill_list",
        "list_files_tree",
        "search_company_documents",
        "search_files_by_name"
    }
)

# Backward-compatible alias
PLAN_MODE_RESEARCH_TOOL_NAMES = DEFAULT_PLAN_MODE_RESEARCH_TOOLS

# Canonical skeleton — must stay aligned with orchestration_protocol.md and markdown_to_plan.
PLAN_MODE_CANONICAL_EXAMPLE = """<plan title="Descriptive project title">
# Execution Plan

## Goal
[Verifiable objective in one or more sentences.]

## Context
[Stack, constraints, risks, out of scope, acceptance criteria.]

## Deliverable
`workspace/project-deliverable.md` — single markdown file; edit incrementally after first create.

## Tasks
- [ ] `task_01` **First concrete atomic action** (deps: none)
- [ ] `task_02` **Second atomic action** (deps: task_01)

## Notes
[Open questions or notes for the reviewer.]
</plan>"""


# Must stay available when AION_PLAN_MODE_TOOL_FIRST=1 (see build_plan_mode_system_prompt).
PLAN_MODE_DRAFT_TOOL_NAMES: FrozenSet[str] = frozenset({"draft_execution_plan"})


def plan_mode_blocked_tool_names() -> set[str]:
    raw = (os.getenv("AION_PLAN_MODE_BLOCKED_TOOLS") or "").strip()
    if raw:
        return {t.strip() for t in raw.split(",") if t.strip()}
    return set(DEFAULT_PLAN_MODE_BLOCKED_TOOLS)


def effective_plan_mode_blocked_tool_names() -> set[str]:
    """Blocked tools for Plan Mode, honoring tool-first invariants."""
    blocked = plan_mode_blocked_tool_names()
    if not plan_mode_tool_first():
        return blocked
    return blocked - set(PLAN_MODE_DRAFT_TOOL_NAMES)


def plan_mode_research_tool_names() -> set[str]:
    """Tool names that count toward the Plan Mode per-turn read-only research budget."""
    raw = (os.getenv("AION_PLAN_MODE_RESEARCH_TOOLS") or "").strip()
    if raw:
        return {t.strip() for t in raw.split(",") if t.strip()}
    return set(DEFAULT_PLAN_MODE_RESEARCH_TOOLS)


def _env_flag(name: str, default: str) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        raw = default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def plan_mode_tool_first() -> bool:
    """When on (default), Plan Mode uses draft_execution_plan tool instead of <plan> tags."""
    if os.getenv("AION_PLAN_MODE_TOOL_FIRST") is not None:
        return _env_flag("AION_PLAN_MODE_TOOL_FIRST", "1")
    try:
        from src.settings import get_settings

        return bool(get_settings().plan_mode_tool_first)
    except Exception:
        return True


def plan_text_parser_enabled() -> bool:
    """Legacy <plan> tag / coercion path. Off by default when tool-first is on."""
    if os.getenv("AION_PLAN_TEXT_PARSER") is not None:
        return _env_flag("AION_PLAN_TEXT_PARSER", "0")
    if plan_mode_tool_first():
        return False
    return True


def plan_mode_max_research_tools() -> int:
    """Max read-only tool calls before emitting <plan> (Cursor-style: plan first, research in tasks)."""
    raw = (os.getenv("AION_PLAN_MODE_MAX_RESEARCH_TOOLS") or "2").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 2
    return max(0, n)


def build_plan_mode_system_prompt() -> str:
    """Injected when resolved_agent_mode == plan (see src/main.py get_agent)."""
    budget = plan_mode_max_research_tools()
    research_tools = plan_mode_research_tool_names()
    tool_first = plan_mode_tool_first()
    if tool_first:
        plan_output = (
            "3. **Register the plan** — Call **`draft_execution_plan`** once with structured arguments:\n"
            "   - `goal`: verifiable objective (string)\n"
            "   - `tasks`: **required** JSON array of `{id, title, depends_on[]}` — ids **`task_01`**, `task_02`, …\n"
            "   - **Minimum 6 atomic tasks** for non-trivial work (strategic, multi-file, or multi-domain requests).\n"
            "   - **Never** a single catch-all task titled `main` or one task that hides many steps.\n"
            "   The tool writes the plan to the sidebar. In chat write only a **2–3 line summary**.\n"
        )
    else:
        plan_output = (
            "3. **Structured plan** — Use `## Goal`, `## Context`, `## Tasks`, `## Notes` "
            "or a `<plan>...</plan>` wrapper. The system registers the plan automatically.\n"
        )
    if not tool_first:
        text_parser_note = f"\n### Skeleton example\n{PLAN_MODE_CANONICAL_EXAMPLE}\n"
    elif plan_text_parser_enabled():
        text_parser_note = (
            "\n### Legacy text format (fallback only)\n"
            f"If you cannot call the tool, you may emit one `<plan>` block:\n{PLAN_MODE_CANONICAL_EXAMPLE}\n"
        )
    else:
        text_parser_note = ""
    return (
        "\n\n## ⚠️ PLAN MODE ACTIVE ⚠️\n"
        "You are in **PLAN MODE**: do **not** deliver the final artifact (Word, PDF, code, full course). "
        "Produce a reviewable plan in the sidebar (**Plan**), then **STOP**.\n\n"
        "### Required flow\n"
        "1. **Clarifications (if needed)** — At most **3 questions** before tools if scope is unclear.\n"
        "2. **Minimal research (read-only)** — At most "
        f"**{budget}** exploration tool calls ({', '.join(sorted(research_tools))}). "
        "**`skill_view` is disabled** in Plan Mode.\n"
        f"{plan_output}"
        "4. **Stop** — No deliverable prose, scripts, or file generation in this turn.\n\n"
        "### Do NOT in this turn\n"
        f"❌ More than {budget} exploration tools before registering the plan\n"
        "❌ `skill_view`, long web research series, Python/docx generation, sandbox writes\n"
        "❌ Reusing old proposals — write a fresh plan for the **current** request\n\n"
        f"{text_parser_note}"
        "### Precedence\n"
        "PLAN MODE overrides artifact_protocol and Sequential Mode.\n"
    )
