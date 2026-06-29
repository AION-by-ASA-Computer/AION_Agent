"""Recover plan sidebar registration when the model omits `<plan>` tags."""

from __future__ import annotations

import re
import uuid
from typing import List, Optional, Tuple

from src.a2a.plan_markdown import (
    markdown_to_plan,
    parse_task_checkbox_line,
    plan_to_markdown,
)
from src.a2a.protocol import ExecutionPlan, ExecutionTask

_TASK_LOOSE_CHECKBOX = re.compile(
    r"^\s*-\s*\[[ xX]\]\s*(?:\*\*)?"
    r"(?:(?:Task\s*)?(?P<num>\d+)|`?(?P<tid>task_\d+)`?)"
    r"\s*[:—\-–]\s*"
    r"(?:\*\*)?(?P<title>.+?)(?:\*\*)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TASK_LOOSE_NUMBERED = re.compile(
    r"^\s*(?:\*\*)?(?:Task\s*)(\d+)\s*[—\-–:]\s*(.+?)(?:\*\*)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TASK_BOLD_ID = re.compile(
    r"^\s*\*\*(?:`(?P<id>task_\d+)`|(?P<id2>task_\d+))\*\*\s*:?\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
_PLAN_TITLE_LINE = re.compile(
    r"^(?:#+\s*)?(?:piano\s+(?:di\s+)?(?:esecuzione|lavoro)?\s*[:\-]?\s*)?(.+)$",
    re.IGNORECASE,
)


def response_has_plan_tag(text: str) -> bool:
    return "<plan" in (text or "").lower()


def looks_like_chat_plan(text: str) -> bool:
    """Heuristic: model emitted a plan in prose without `<plan>` wrapper."""
    body = (text or "").strip()
    if not body:
        return False
    if re.match(r"^plan\s+title\s*=", body, re.IGNORECASE):
        return True
    if response_has_plan_tag(body):
        return False
    from src.runtime.plan_mode_guard import response_looks_like_deliverable_leak

    if response_looks_like_deliverable_leak(body):
        return False
    low = body.lower()
    bold_id_hits = len(_TASK_BOLD_ID.findall(body))
    if "## tasks" in low and re.search(r"^\s*-\s*\[[ xX]\]\s+", body, re.MULTILINE):
        return True
    if "## task" in low and (
        bold_id_hits >= 1 or re.search(r"^\s*-\s*\[[ xX]\]\s+", body, re.MULTILINE)
    ):
        return True
    if ("## obiettivo" in low or "## goal" in low) and (
        bold_id_hits >= 1
        or re.search(r"^\s*-\s*\[[ xX]\]\s+", body, re.MULTILINE)
        or re.search(r"^\s*#+\s*piano", body, re.MULTILINE | re.IGNORECASE)
    ):
        return True
    task_hits = len(_TASK_LOOSE_NUMBERED.findall(body))
    if task_hits >= 2:
        return True
    checkbox_hits = len(_TASK_LOOSE_CHECKBOX.findall(body))
    if checkbox_hits >= 2:
        return True
    if bold_id_hits >= 1 and (
        "piano" in low or "## task" in low or "## obiettivo" in low
    ):
        return True
    if ("piano di esecuzione" in low or "piano di lavoro" in low) and task_hits >= 1:
        return True
    if re.match(r"^#+\s*piano\b", body, re.IGNORECASE) and (
        bold_id_hits >= 1 or task_hits >= 1
    ):
        return True
    return False


def _extract_loose_tasks(text: str) -> List[ExecutionTask]:
    tasks: List[ExecutionTask] = []
    seen: set[str] = set()
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        parsed = parse_task_checkbox_line(raw)
        if parsed:
            tid, title, _done = parsed
            if title and len(title) >= 3:
                if tid in seen:
                    tid = f"task_{len(tasks) + 1:02d}"
                seen.add(tid)
                tasks.append(
                    ExecutionTask(
                        id=tid,
                        title=title[:240],
                        description="",
                        depends_on=[],
                        target_profile=None,
                    )
                )
            continue
        bold_m = _TASK_BOLD_ID.match(raw)
        if bold_m:
            tid = (bold_m.group("id") or bold_m.group("id2") or "").strip()
            title = (bold_m.group("title") or "").strip()
            if tid and title and len(title) >= 3:
                if tid in seen:
                    tid = f"task_{len(tasks) + 1:02d}"
                seen.add(tid)
                tasks.append(
                    ExecutionTask(
                        id=tid,
                        title=title[:240],
                        description="",
                        depends_on=[],
                        target_profile=None,
                    )
                )
            continue
        m2 = _TASK_LOOSE_NUMBERED.match(raw)
        if not m2:
            continue
        num = (m2.group(1) or str(len(tasks) + 1)).strip()
        title = (m2.group(2) or "").strip()
        if not title or len(title) < 3:
            continue
        tid = f"task_{num.zfill(2)}" if num.isdigit() else f"task_{len(tasks) + 1:02d}"
        if tid in seen:
            tid = f"task_{len(tasks) + 1:02d}"
        seen.add(tid)
        tasks.append(
            ExecutionTask(
                id=tid,
                title=title[:240],
                description="",
                depends_on=[],
                target_profile=None,
            )
        )
    return tasks


def _infer_goal(text: str, title: str) -> str:
    if title.strip():
        return title.strip()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if _TASK_LOOSE_NUMBERED.match(s) or _TASK_LOOSE_CHECKBOX.match(s):
            break
        if len(s) > 20 and "task " not in s.lower()[:8]:
            return s[:500]
    return "Execution plan"


def _infer_title(text: str) -> str:
    for line in text.splitlines()[:12]:
        s = line.strip()
        if not s:
            continue
        if "piano" in s.lower() and (":" in s or "—" in s or "-" in s):
            parts = re.split(r"[:\-—]", s, maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                return parts[1].strip()[:120]
            m = _PLAN_TITLE_LINE.match(s)
            if m and m.group(1).strip():
                return m.group(1).strip()[:120]
        if s.startswith("#"):
            return s.lstrip("#").strip()[:120]
    return "Execution plan"


def coerce_chat_plan_to_canonical_markdown(
    text: str,
    *,
    title: Optional[str] = None,
) -> Optional[str]:
    """
    Wrap chat-only plan prose into `<plan>` + canonical sections for markdown_to_plan.
    Returns None if coercion is not possible.
    """
    body = (text or "").strip()
    if not body or response_has_plan_tag(body):
        return None
    body = _normalize_pseudo_plan_open(body)

    # First try: response already contains structured sections (## Goal / ## Tasks)
    # but without the required <plan> wrapper.
    low = body.lower()
    if any(
        marker in low
        for marker in ("## tasks", "## task", "## goal", "## obiettivo", "## contesto")
    ):
        try:
            parsed = markdown_to_plan(body)
            plan_title = (title or _infer_title(body)).strip() or "Execution plan"
            inner = plan_to_markdown(parsed)
            return f'<plan title="{_escape_attr(plan_title)}">\n{inner}\n</plan>'
        except Exception:
            pass

    tasks = _extract_loose_tasks(body)
    if not tasks:
        return None
    plan_title = (title or _infer_title(body)).strip() or "Execution plan"
    goal = _infer_goal(body, plan_title)
    plan = ExecutionPlan(goal=goal, tasks=tasks)
    inner = plan_to_markdown(plan)
    return f'<plan title="{_escape_attr(plan_title)}">\n{inner}\n</plan>'


def _escape_attr(value: str) -> str:
    return (value or "").replace('"', "'").replace("\n", " ")[:200]


def _normalize_pseudo_plan_open(text: str) -> str:
    """
    Normalize malformed pseudo-openers like:
      plan title="X"
    into plain markdown body (drop first line), so markdown_to_plan can parse sections.
    """
    body = (text or "").strip()
    if not body:
        return text
    m = re.match(
        r'^plan\s+title\s*=\s*"([^"]*)"\s*>?\s*\n(.*)$',
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(2).lstrip()
    lines = body.splitlines()
    if not lines:
        return text
    first = lines[0].strip().lower()
    if first.startswith("plan ") and "## goal" in body.lower():
        return "\n".join(lines[1:]).lstrip()
    return text


def new_execution_plan_id() -> str:
    return "execution_plan_" + uuid.uuid4().hex[:8]
