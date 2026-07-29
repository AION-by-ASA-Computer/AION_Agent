"""Plan execution reminders and helpers (post-approve, one task per turn)."""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from src.runtime.plan_engine import next_pending_task_id

_TASK_TITLE_RE = re.compile(r"\*\*([^*]+)\*\*")
_DONE_WHEN_RE = re.compile(
    r"(?:done\s+when|exit\s+criteria|completato\s+quando)\s*:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
_PLACEHOLDER_DELIVERABLE = re.compile(
    r"^_?percorso file unico|^_?contesto, vincoli|placeholder",
    re.IGNORECASE,
)


def plan_exec_max_tool_calls() -> int:
    raw = (os.getenv("AION_PLAN_EXEC_MAX_TOOL_CALLS") or "24").strip()
    try:
        return max(4, int(raw))
    except ValueError:
        return 24


def infer_deliverable_path(plan_markdown: str) -> Optional[str]:
    """Best-effort path for the deliverable referenced in the plan."""
    md = plan_markdown or ""
    for pat in (
        r"`(workspace/[^`]+?\.(?:md|markdown|xlsx?|csv|html|docx?))`",
        r"#\s*filename:\s*(\S+\.(?:md|markdown|xlsx?|csv|html|docx?))",
        r"(workspace/[\w./-]+\.(?:md|markdown|xlsx?|csv|html|docx?))",
    ):
        m = re.search(pat, md, re.IGNORECASE)
        if m:
            path = m.group(1).strip()
            if not path.startswith("workspace/"):
                path = f"workspace/{path.lstrip('/')}"
            return path
    goal = extract_goal_from_markdown(md)
    slug = re.sub(r"[^a-z0-9]+", "-", (goal or "deliverable").lower()).strip("-")[:48]
    return f"workspace/{slug or 'deliverable'}.md" if slug else None


def extract_goal_from_markdown(plan_markdown: str) -> str:
    """First paragraph under ## Goal."""
    md = plan_markdown or ""
    mode = False
    buf: List[str] = []
    for raw in md.splitlines():
        line = raw.strip()
        sl = line.lower()
        if sl == "## goal":
            mode = True
            continue
        if line.startswith("## ") and sl != "## goal":
            break
        if mode and line:
            buf.append(line)
    return " ".join(buf).strip()[:500]


def task_title_from_markdown(plan_markdown: str, task_id: str) -> str:
    tid = (task_id or "").strip()
    if not tid:
        return ""
    for line in (plan_markdown or "").splitlines():
        if f"`{tid}`" not in line:
            continue
        m = _TASK_TITLE_RE.search(line)
        if m:
            return m.group(1).strip()
    return ""


def task_description_from_markdown(plan_markdown: str, task_id: str) -> str:
    """Task description from parsed plan (``Description:`` sub-line)."""
    tid = (task_id or "").strip()
    if not tid:
        return ""
    try:
        from src.a2a.plan_markdown import markdown_to_plan

        plan = markdown_to_plan(plan_markdown or "")
        for t in plan.tasks:
            if t.id == tid:
                return (t.description or "").strip()
    except Exception:
        pass
    return ""


def iter_pending_tasks_after(
    plan_markdown: str,
    current_task_id: str,
    *,
    limit: int = 5,
) -> List[Tuple[str, str]]:
    """Pending tasks after ``current_task_id`` as (id, title) pairs."""
    from src.runtime.orchestration_tools import iter_plan_task_rows

    tid = (current_task_id or "").strip()
    rows = iter_plan_task_rows(plan_markdown or "")
    found_current = False
    out: List[Tuple[str, str]] = []
    for row_id, title, done in rows:
        if row_id == tid:
            found_current = True
            continue
        if not found_current:
            continue
        if done:
            continue
        out.append((row_id, title))
        if len(out) >= limit:
            break
    if not found_current:
        for row_id, title, done in rows:
            if done or row_id == tid:
                continue
            out.append((row_id, title))
            if len(out) >= limit:
                break
    return out


def extract_done_when(description: str, *, fallback_title: str = "") -> str:
    """Parse Done when / exit criteria from task description."""
    desc = (description or "").strip()
    m = _DONE_WHEN_RE.search(desc)
    if m:
        return m.group(1).strip().split("\n")[0][:400]
    if desc:
        first = desc.split("\n")[0].strip()
        if len(first) > 20:
            return first[:400]
    title = (fallback_title or "").strip()
    if title:
        return (
            f"The objective in the task title is verifiably complete: {title}. "
            "Then call mark_task_completed and STOP."
        )
    return (
        "The current task objective is verifiably complete. "
        "Then call mark_task_completed and STOP."
    )


def _is_research_task(title: str, description: str) -> bool:
    blob = f"{title} {description}".lower()
    research_kw = (
        "research",
        "ricerca",
        "search",
        "collect",
        "gather",
        "find sources",
        "analizza",
        "explore",
    )
    return any(k in blob for k in research_kw)


def build_plan_execution_reminder(
    *,
    plan_id: str,
    plan_markdown: str,
    next_task_id: Optional[str] = None,
    phase: str = "start",
) -> str:
    """System reminder injected on internal_trigger / continue execution."""
    md = plan_markdown or ""
    ntid = (next_task_id or next_pending_task_id(md) or "").strip()
    title = task_title_from_markdown(md, ntid) if ntid else ""
    description = task_description_from_markdown(md, ntid) if ntid else ""
    deliverable = infer_deliverable_path(md) or "workspace/deliverable.md"
    goal = extract_goal_from_markdown(md)
    later = iter_pending_tasks_after(md, ntid, limit=5)
    done_when = extract_done_when(description, fallback_title=title)

    lines: List[str] = [
        "<system-reminder>",
        f"Plan `{plan_id}` — execution turn ({phase}).",
        "",
        "## Goal",
        goal or "(see plan sidebar)",
        "",
        "## Current task (ONLY this turn)",
        f"- **ID:** `{ntid}`",
    ]
    if title:
        lines.append(f"- **Title:** {title}")
    if description:
        lines.append(f"- **Description:** {description}")
    lines.append(f"- **Deliverable SSOT:** `{deliverable}`")
    lines.append("")

    if _is_research_task(title, description):
        lines.extend(
            [
                "## Do now",
                "- Use read-only research tools (web_search, web_fetch_page, grep, read files) "
                "only as needed for THIS task.",
                "- Save structured findings to workspace files if the task requires persistence.",
                "- Do NOT generate the final deliverable unless this task title explicitly says so.",
            ]
        )
    else:
        lines.extend(
            [
                "## Do now",
                f"- Complete the work described for `{ntid}` only.",
                f"- If `{deliverable}` does NOT exist: create it ONCE (artifact block or sandbox_write).",
                "- If it ALREADY exists: use ONLY `sandbox_edit_workspace_file` (surgical edits).",
                "- Do NOT paste the full document body in chat — edits go to the file only.",
            ]
        )
    lines.append("")

    if later:
        lines.append("## Out of scope / Later (do NOT execute now)")
        lines.append(
            "These pending tasks will run in separate turns and will use your output. "
            "Do NOT start them in this turn:"
        )
        for lid, ltitle in later:
            lines.append(f"- `{lid}` — {ltitle}")
        lines.append("")

    if later:
        nxt_id, nxt_title = later[0]
        lines.extend(
            [
                "## Handoff for next task",
                f"Leave clear, reusable output in workspace for `{nxt_id}` ({nxt_title}).",
                f"Primary artifact path: `{deliverable}`.",
                "Prefer structured files/sections over chat-only summaries.",
                "",
            ]
        )

    lines.extend(
        [
            "## Done when",
            done_when,
            "",
            "## Exit (mandatory)",
            f'1. When Done when is satisfied, call `mark_task_completed(task_id="{ntid}")`.',
            "2. Immediately STOP — zero more tool calls after mark_task_completed.",
            "3. Do NOT start the next task in this turn (the server schedules it).",
            "</system-reminder>",
        ]
    )
    return "\n".join(lines)


def build_plan_execution_trigger(
    task_id: str,
    *,
    attempt: int = 0,
) -> str:
    """User trigger text for a plan execution turn."""
    tid = (task_id or "").strip()
    if attempt <= 0:
        return (
            f"Execute plan task `{tid}` only. "
            "Follow the system-reminder brief (scope, out-of-scope, Done when, Exit). "
            f'When Done when is met, call mark_task_completed(task_id="{tid}") and STOP.'
        )
    return (
        f"Retry plan task `{tid}` only. "
        "Complete the Done when criteria from the system-reminder before marking. "
        f"Do NOT call mark_task_completed unless the task is truly complete. "
        f'When done, call mark_task_completed(task_id="{tid}") and STOP immediately.'
    )
