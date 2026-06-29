"""Plan Mode engine: phase controller, mandatory finalizer, SSE helpers."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from src.a2a.plan_markdown import markdown_to_plan, plan_to_markdown
from src.a2a.protocol import ExecutionPlan, ExecutionTask
from src.runtime.plan_coercion import (
    coerce_chat_plan_to_canonical_markdown,
    looks_like_chat_plan,
    new_execution_plan_id,
)
from src.runtime.plan_mode import (
    plan_mode_max_research_tools,
    plan_mode_research_tool_names,
)

logger = logging.getLogger(__name__)

PlanPhase = Literal[
    "clarifying",
    "researching",
    "drafting",
    "finalizing",
    "registered",
    "research_budget_reached",
    "error",
]

FinalizeSource = Literal["tag", "llm_json", "coercion", "fallback", "failed"]

_PLAN_BODY_MARKERS = re.compile(
    r"(?:^|\n)\s*(?:#+\s*piano\b|##\s*(?:task|tasks|goal|obiettivo)\b|\*\*task_\d+)",
    re.IGNORECASE,
)

PLAN_FINALIZE_PROMPT = """\
You extract a structured execution plan from the assistant draft below.

**User question:** {user_message}

**Assistant draft:**
{draft}

Return ONLY a JSON object with:
- "goal": string (verifiable objective)
- "context": string (optional background)
- "tasks": array of objects with "id" (task_01, task_02, ...), "title", "depends_on" (array of task ids)

Example:
{{
  "goal": "Document WWDC 2026 announcements",
  "context": "Markdown deliverable for Italian readers",
  "tasks": [
    {{"id": "task_01", "title": "Collect official sources", "depends_on": []}},
    {{"id": "task_02", "title": "Write platform sections", "depends_on": ["task_01"]}}
  ]
}}
"""


@dataclass
class FinalizeResult:
    markdown: str
    source: FinalizeSource
    needs_review: bool = False
    tasks_count: int = 0
    plan_id: Optional[str] = None


def plan_finalize_llm_enabled() -> bool:
    return os.getenv("AION_PLAN_FINALIZE_LLM", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def plan_finalizer_timeout_sec() -> float:
    """LLM timeout for PlanFinalizer (was hardcoded 90s). Default 20s per IMPROVEMENTS Fase A."""
    raw = (os.getenv("AION_PLAN_FINALIZER_TIMEOUT_SEC") or "20").strip()
    try:
        val = float(raw)
    except ValueError:
        val = 20.0
    return max(5.0, min(val, 120.0))


PLAN_FINALIZE_USER_MESSAGE = (
    "I could not structure a valid execution plan from this response. "
    "Can you rephrase the request or ask me to try again?"
)


def should_suppress_plan_token(piece: str, accumulated: str) -> bool:
    """Hide plan-like streaming tokens from chat in Plan Mode."""
    if not piece and not accumulated:
        return False
    combined = (accumulated or "") + (piece or "")
    if _PLAN_BODY_MARKERS.search(combined):
        return True
    return looks_like_chat_plan(combined)


def next_pending_task_id(markdown: str) -> Optional[str]:
    from src.runtime.orchestration_tools import iter_plan_task_rows

    for tid, _title, done in iter_plan_task_rows(markdown):
        if not done:
            return tid
    return None


class PlanModeController:
    """Tracks Plan Mode phases, research budget, and incremental preview SSE."""

    def __init__(self, *, plan_id: Optional[str] = None) -> None:
        self.plan_id = (plan_id or new_execution_plan_id()).strip()
        self.phase: PlanPhase = "clarifying"
        self.research_count = 0
        self.budget = plan_mode_max_research_tools()
        self.research_tools = plan_mode_research_tool_names()
        self.budget_exhausted = False
        self._last_progress_len = 0
        self._progress_interval = int(os.getenv("AION_PLAN_PROGRESS_MIN_CHARS", "120"))
        self._revision = 0

    def is_research_tool(self, name: str) -> bool:
        return (name or "").strip() in self.research_tools

    def on_research_tool_start(self, name: str) -> tuple[bool, Optional[str]]:
        if not self.is_research_tool(name):
            return True, None
        if self.research_count >= self.budget:
            self.budget_exhausted = True
            self.phase = "research_budget_reached"
            return (
                False,
                f"Plan Mode: research budget reached ({self.budget} read-only tools). "
                "Stop research and finalize the plan.",
            )
        self.research_count += 1
        self.phase = "researching"
        return True, None

    def research_budget_reminder(self) -> str:
        return (
            "<system-reminder>\n"
            f"Plan Mode research budget reached ({self.budget} tools). "
            "Stop web_search/web_fetch and finalize the execution plan now.\n"
            "</system-reminder>"
        )

    def sse_phase(
        self, phase: PlanPhase, *, message: Optional[str] = None
    ) -> Dict[str, Any]:
        self.phase = phase
        out: Dict[str, Any] = {
            "type": "plan_phase",
            "phase": phase,
            "plan_id": self.plan_id,
        }
        if message:
            out["message"] = message
        return out

    def sse_progress(
        self,
        markdown: str,
        *,
        tasks_count: Optional[int] = None,
        revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.phase = "drafting"
        if revision is not None:
            self._revision = revision
        else:
            self._revision += 1
        out: Dict[str, Any] = {
            "type": "plan_progress",
            "plan_markdown": markdown,
            "plan_id": self.plan_id,
            "revision": self._revision,
        }
        if tasks_count is not None:
            out["tasks_count"] = tasks_count
        return out

    def sse_plan_error(self, message: str) -> Dict[str, Any]:
        self.phase = "error"
        return {
            "type": "plan_error",
            "plan_id": self.plan_id,
            "message": message,
        }

    def next_revision(self) -> int:
        self._revision += 1
        return self._revision

    def maybe_progress_sse(self, full_text: str) -> Optional[Dict[str, Any]]:
        body = (full_text or "").strip()
        if not body or not looks_like_chat_plan(body):
            return None
        if len(body) - self._last_progress_len < self._progress_interval:
            return None
        self._last_progress_len = len(body)
        tasks_count: Optional[int] = None
        try:
            coerced = coerce_chat_plan_to_canonical_markdown(body)
            if coerced:
                tasks_count = len(markdown_to_plan(coerced).tasks)
        except Exception:
            pass
        return self.sse_progress(body, tasks_count=tasks_count)


_THINK_STRIP = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)
# <<plan ...> is a malformed plan tag sometimes emitted by the model; strip it to avoid
# it being recycled into the NEXT plan's text via PlanFinalizer.
_MALFORMED_PLAN_TAG = re.compile(r"<<plan\b[^>]*>", re.IGNORECASE)


def _sanitize_plan_finalizer_input(text: str) -> str:
    """Remove reasoning artifacts that the model may leak into the text stream."""
    t = _THINK_STRIP.sub("", text)
    t = _THINK_CLOSE.sub("", t)
    t = _MALFORMED_PLAN_TAG.sub("", t)
    # Truncate at a second <plan or <plan title= to avoid duplicated plan fragments.
    first_plan = t.find("<plan")
    if first_plan != -1:
        second_plan = t.find("<plan", first_plan + 5)
        if second_plan != -1:
            t = t[:second_plan]
    return t.strip()


class PlanFinalizer:
    """Mandatory end-of-turn plan extraction (LLM JSON → coercion → minimal fallback)."""

    @staticmethod
    async def finalize(
        full_text: str,
        *,
        user_message: str = "",
        title: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> Optional[FinalizeResult]:
        body = _sanitize_plan_finalizer_input(full_text or "")
        pid = (plan_id or new_execution_plan_id()).strip()

        if plan_finalize_llm_enabled() and body:
            llm_result = await PlanFinalizer._llm_finalize(
                body, user_message=user_message, title=title, plan_id=pid
            )
            if llm_result:
                return llm_result

        coerced = (
            coerce_chat_plan_to_canonical_markdown(body, title=title) if body else None
        )
        if coerced:
            try:
                plan = markdown_to_plan(coerced)
                return FinalizeResult(
                    markdown=coerced,
                    source="coercion",
                    tasks_count=len(plan.tasks),
                    plan_id=pid,
                )
            except Exception as exc:
                logger.debug("coerced plan parse failed: %s", exc)

        if body:
            try:
                plan = markdown_to_plan(body)
                if plan.tasks:
                    from src.runtime.plan_coercion import _escape_attr, _infer_title

                    plan_title = (
                        title or _infer_title(body)
                    ).strip() or "Execution plan"
                    inner = plan_to_markdown(plan)
                    wrapped = (
                        f'<plan title="{_escape_attr(plan_title)}">\n{inner}\n</plan>'
                    )
                    return FinalizeResult(
                        markdown=wrapped,
                        source="coercion",
                        tasks_count=len(plan.tasks),
                        plan_id=pid,
                    )
            except Exception:
                pass

        logger.info(
            "PlanFinalizer: no valid plan extracted (plan_id=%s, body_len=%s)",
            pid,
            len(body),
        )
        return None

    @staticmethod
    async def _llm_finalize(
        draft: str,
        *,
        user_message: str = "",
        title: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> Optional[FinalizeResult]:
        try:
            from src.research.llm_bridge import complete_messages

            prompt = PLAN_FINALIZE_PROMPT.format(
                user_message=(user_message or "N/A")[:2000],
                draft=(draft or "")[:12000],
            )
            raw = await complete_messages(
                [
                    {"role": "system", "content": "You output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=4096,
                timeout=plan_finalizer_timeout_sec(),
            )
            data = PlanFinalizer._parse_json_object(raw)
            if not data:
                return None
            goal = str(data.get("goal") or "Execution plan").strip()
            tasks_raw = data.get("tasks") or []
            tasks: List[ExecutionTask] = []
            for i, row in enumerate(tasks_raw):
                if not isinstance(row, dict):
                    continue
                tid = str(row.get("id") or f"task_{i + 1:02d}").strip()
                ttitle = str(row.get("title") or f"Task {i + 1}").strip()
                deps = [
                    str(x).strip()
                    for x in (row.get("depends_on") or [])
                    if str(x).strip()
                ]
                tasks.append(
                    ExecutionTask(
                        id=tid,
                        title=ttitle[:240],
                        description=str(row.get("description") or "").strip(),
                        depends_on=deps,
                        target_profile=None,
                    )
                )
            if not tasks:
                return None
            plan = ExecutionPlan(goal=goal, tasks=tasks)
            from src.runtime.plan_coercion import _escape_attr, _infer_title

            plan_title = (title or _infer_title(draft)).strip() or goal[:120]
            inner = plan_to_markdown(plan)
            ctx = str(data.get("context") or "").strip()
            if ctx:
                inner = inner.replace(
                    "_Context, constraints, and background notes (markdown consentito). Edit long explanations here._",
                    ctx,
                )
            wrapped = f'<plan title="{_escape_attr(plan_title)}">\n{inner}\n</plan>'
            return FinalizeResult(
                markdown=wrapped,
                source="llm_json",
                tasks_count=len(tasks),
                plan_id=(plan_id or "").strip() or None,
            )
        except Exception as exc:
            logger.warning("PlanFinalizer LLM path failed: %s", exc)
            return None

    @staticmethod
    def _parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
        text = (raw or "").strip()
        if not text:
            return None
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
