"""Plan execution reminders and helpers (post-approve, one task per turn)."""
from __future__ import annotations

import os
import re
from typing import Optional

from src.runtime.plan_engine import next_pending_task_id

_TASK_TITLE_RE = re.compile(r"\*\*([^*]+)\*\*")
_DELIVERABLE_PATH_RE = re.compile(
    r"(?:workspace/)?[\w./-]+\.(?:md|markdown|html|docx?)\b",
    re.IGNORECASE,
)


def plan_exec_max_tool_calls() -> int:
    raw = (os.getenv("AION_PLAN_EXEC_MAX_TOOL_CALLS") or "16").strip()
    try:
        return max(4, int(raw))
    except ValueError:
        return 16


def infer_deliverable_path(plan_markdown: str) -> Optional[str]:
    """Best-effort path for the markdown deliverable referenced in the plan."""
    md = plan_markdown or ""
    for pat in (
        r"`(workspace/[^`]+?\.(?:md|markdown))`",
        r"#\s*filename:\s*(\S+\.(?:md|markdown))",
        r"(workspace/[\w./-]+\.(?:md|markdown))",
    ):
        m = re.search(pat, md, re.IGNORECASE)
        if m:
            path = m.group(1).strip()
            if not path.startswith("workspace/"):
                path = f"workspace/{path.lstrip('/')}"
            return path
    goal = ""
    for line in md.splitlines():
        if line.strip().lower().startswith("## goal"):
            continue
        if line.strip().startswith("## "):
            break
        if line.strip():
            goal = (goal + " " + line.strip()).strip()
    slug = re.sub(r"[^a-z0-9]+", "-", (goal or "deliverable").lower()).strip("-")[:48]
    return f"workspace/{slug or 'deliverable'}.md" if slug else None


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


def build_plan_execution_reminder(
    *,
    plan_id: str,
    plan_markdown: str,
    next_task_id: Optional[str] = None,
    phase: str = "start",
) -> str:
    """System reminder injected on internal_trigger / continue execution."""
    ntid = (next_task_id or next_pending_task_id(plan_markdown) or "").strip()
    title = task_title_from_markdown(plan_markdown, ntid) if ntid else ""
    deliverable = infer_deliverable_path(plan_markdown) or "workspace/deliverable.md"
    task_line = f"`{ntid}` — {title}" if title else f"`{ntid}`"
    return (
        "<system-reminder>\n"
        f"Plan `{plan_id}` — execution turn ({phase}).\n"
        f"Execute ONLY task {task_line} in this turn.\n"
        "Rules:\n"
        "1. Call `mark_task_completed(task_id=...)` when this single task is done, then STOP.\n"
        "2. Do NOT start the next task in the same turn.\n"
        "3. Markdown deliverable SSOT: "
        f"`{deliverable}`.\n"
        "   - If the file does NOT exist yet: create it ONCE (fenced artifact with "
        "`# artifact_id`, `# title`, `# filename` OR one `sandbox_write_workspace_file`).\n"
        "   - If the file ALREADY exists: use ONLY `sandbox_edit_workspace_file` "
        "(surgical edits). Never rewrite the full document.\n"
        "4. Do NOT paste the full document body in chat — edits go to the file only.\n"
        "5. Research tools are allowed only if required by the current task title.\n"
        "</system-reminder>"
    )
