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


# Document formats a plan may deliver, ranked: final/binary formats first, then
# web pages, then working formats. Lower rank wins when several are mentioned.
_DELIVERABLE_EXT_RANK = {
    "docx": 0,
    "doc": 0,
    "pptx": 0,
    "xlsx": 0,
    "xls": 0,
    "pdf": 0,
    "html": 1,
    "md": 2,
    "markdown": 2,
    "csv": 2,
}
_DELIVERABLE_EXT_ALT = "|".join(sorted(_DELIVERABLE_EXT_RANK, key=len, reverse=True))
# A workspace path ending in a deliverable extension; the lookahead stops at the
# extension so trailing sentence punctuation ("….md.") is not captured.
_WORKSPACE_PATH_RE = re.compile(
    rf"(workspace/[\w./-]+?\.(?:{_DELIVERABLE_EXT_ALT}))(?![\w])", re.IGNORECASE
)
_FILENAME_HINT_RE = re.compile(
    rf"#\s*filename:\s*(\S+?\.(?:{_DELIVERABLE_EXT_ALT}))(?![\w])", re.IGNORECASE
)


def _strip_template_placeholders(md: str) -> str:
    """Drop the italic hint lines that plan_to_markdown writes as section templates.

    ``plan_to_markdown`` fills ``## Context`` / ``## Deliverable`` with italic
    placeholders such as "_Percorso file unico …, es. `workspace/progetto.md` …_".
    When the agent never replaces them, the example path used to be taken as
    the real deliverable (every plan "delivered" workspace/progetto.md).
    """
    kept: List[str] = []
    for line in (md or "").splitlines():
        s = line.strip()
        is_italic_hint = len(s) > 2 and s.startswith("_") and s.endswith("_")
        if is_italic_hint and _PLACEHOLDER_DELIVERABLE.search(s.strip("_ ")):
            continue
        kept.append(line)
    return "\n".join(kept)


def _markdown_section(md: str, heading: str) -> str:
    """Body of the ``## <heading>`` section (case-insensitive), or ''."""
    out: List[str] = []
    inside = False
    for raw in (md or "").splitlines():
        s = raw.strip()
        if s.startswith("## "):
            if inside:
                break
            inside = s[3:].strip().lower() == heading.lower()
            continue
        if inside:
            out.append(raw)
    return "\n".join(out)


def _deliverable_rank(path: str) -> int:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _DELIVERABLE_EXT_RANK.get(ext, 99)


def infer_deliverable_path(plan_markdown: str) -> Optional[str]:
    """Best-effort path of the plan's final document (``workspace/…``).

    Used for the per-task brief (so writing tasks target the right file) and
    for the completion summary. Order:

    1. a path written in the ``## Deliverable`` section (template hint ignored);
    2. otherwise, among the workspace paths mentioned anywhere in the plan, the
       best-ranked format (docx/pptx/xlsx/pdf > html > md/csv), the last
       mention winning ties — later tasks produce the final output;
    3. a ``# filename:`` hint;
    4. a slug of the goal (``workspace/<goal-slug>.md``).
    """
    md = _strip_template_placeholders(plan_markdown or "")

    # 1. Explicit Deliverable section.
    section = _markdown_section(md, "Deliverable")
    m = _WORKSPACE_PATH_RE.search(section)
    if m:
        return m.group(1).strip()

    # 2. Best-ranked path mentioned in the plan (last mention breaks ties).
    best: Optional[Tuple[int, int, str]] = None
    for idx, pm in enumerate(_WORKSPACE_PATH_RE.finditer(md)):
        path = pm.group(1).strip()
        key = (_deliverable_rank(path), -idx, path)
        if best is None or key < best:
            best = key
    if best is not None:
        return best[2]

    # 3. "# filename: x.md" hint.
    fm = _FILENAME_HINT_RE.search(md)
    if fm:
        return f"workspace/{fm.group(1).strip().lstrip('/')}"

    # 4. Fallback derived from the goal.
    goal = extract_goal_from_markdown(md)
    slug = re.sub(r"[^a-z0-9]+", "-", (goal or "deliverable").lower()).strip("-")[:48]
    return f"workspace/{slug or 'deliverable'}.md" if slug else None


def resolve_existing_deliverable(
    session_id: str, inferred: Optional[str]
) -> Optional[str]:
    """Return a deliverable path that actually exists in the session workspace.

    Keeps ``inferred`` when that file exists. Otherwise picks the best existing
    document in ``workspace/`` (same format ranking as
    :func:`infer_deliverable_path`, newest file first), ignoring hidden folders
    such as ``.versions``. Falls back to ``inferred`` when nothing matches or the
    session cannot be resolved. Paths are relative to the session root
    (``workspace/…``), the form used for attachments' ``storage_key``.
    """
    try:
        from src.session_workspace import normalize_session_id, session_root

        root = session_root(normalize_session_id(session_id))
    except Exception:
        return inferred
    if inferred:
        try:
            candidate = (root / inferred).resolve()
            if candidate.is_file() and root.resolve() in candidate.parents:
                return inferred
        except OSError:
            pass
    workspace = root / "workspace"
    if not workspace.is_dir():
        return inferred
    best: Optional[Tuple[int, float, str]] = None
    for path in workspace.rglob("*"):
        rel_parts = path.relative_to(workspace).parts
        if any(part.startswith(".") or part == "node_modules" for part in rel_parts):
            continue
        if not path.is_file():
            continue
        rank = _deliverable_rank(path.name)
        if rank >= 99:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        rel = "workspace/" + "/".join(rel_parts)
        key = (rank, -mtime, rel)
        if best is None or key < best:
            best = key
    return best[2] if best else inferred


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
            # The turn is cut right after mark_task_completed, so any text for
            # the user must come before it: it becomes this task's chat answer.
            f"1. When Done when is satisfied, first write a short message for the user "
            f"(2–4 sentences): the outcome of `{ntid}`, files produced (workspace paths) "
            "and key results. Do not paste full document bodies.",
            f'2. Then call `mark_task_completed(task_id="{ntid}")`.',
            "3. Immediately STOP — zero more tool calls after mark_task_completed.",
            "4. Do NOT start the next task in this turn (the server schedules it).",
            "</system-reminder>",
        ]
    )
    return "\n".join(lines)


# Appended to every plan-execution trigger. Plan mode has no dedicated profile,
# so this is the only place to steer how the executing agent produces long
# deliverables. Without it, models with thinking enabled tended to draft the
# whole text (e.g. a ~1000-word article) inside their reasoning, exhaust the
# output token budget and never emit the tool call that writes the file: the
# task then failed on every attempt and the run paused.
_LONG_OUTPUT_GUIDANCE = (
    "If the task produces long text (article, report, document), do not draft it "
    "in your reasoning: write it straight to the workspace file in sections — "
    "sandbox_write_workspace_file for the first section, then "
    "sandbox_append_workspace_file for each following one — keeping every tool "
    "call short."
)


def build_plan_completion_reminder(
    *,
    plan_id: str,
    plan_markdown: str,
    deliverables: Optional[List[str]] = None,
) -> str:
    """System reminder for the plan-closing turn (every task already completed).

    Injected by ``turn_context`` on an ``internal_trigger`` turn when the plan
    has no pending task: instead of a task brief, it asks the agent to close
    the plan with ``complete_execution_plan`` (summary + generated documents).
    """
    md = plan_markdown or ""
    goal = extract_goal_from_markdown(md)
    lines: List[str] = [
        "<system-reminder>",
        f"Plan `{plan_id}` — closing turn. ALL tasks are completed.",
        "",
        "## Goal",
        goal or "(see plan sidebar)",
        "",
    ]
    if deliverables:
        lines.append("## Documents found in the workspace")
        lines.extend(f"- `{p}`" for p in deliverables)
        lines.append("")
    lines.extend(
        [
            "## Do now (mandatory)",
            "1. Do NOT execute tasks, do NOT edit files, do NOT call mark_task_completed.",
            "2. Call `complete_execution_plan` exactly once with:",
            "   - `summary`: the final message for the user in the user's language "
            "(2–5 sentences, markdown): what was produced, key results, where the "
            "documents are. Do not paste document bodies.",
            "   - `deliverables`: workspace paths of the final documents for the user "
            "(final formats first, e.g. .docx/.pdf; skip helper scripts and temp data).",
            "3. Write nothing else: the summary you pass is shown as your answer, "
            "followed by the document cards. The turn ends after the tool.",
            "</system-reminder>",
        ]
    )
    return "\n".join(lines)


def build_plan_completion_trigger(plan_id: str) -> str:
    """User trigger text of the plan-closing turn (see ``build_plan_completion_reminder``)."""
    return (
        f"All tasks of plan `{(plan_id or '').strip()}` are completed. "
        "Close the plan now: call complete_execution_plan with the final summary "
        "for the user and the generated documents, as described in the "
        "system-reminder. No other tool calls."
    )


def build_plan_execution_trigger(
    task_id: str,
    *,
    attempt: int = 0,
) -> str:
    """User trigger text for a plan execution turn.

    ``attempt`` is 0 for the first try and >0 for the retry issued by the plan
    execution handler when the task was not marked completed. Both variants end
    with the long-output guidance (see ``_LONG_OUTPUT_GUIDANCE``).
    """
    tid = (task_id or "").strip()
    if attempt <= 0:
        return (
            f"Execute plan task `{tid}` only. "
            "Follow the system-reminder brief (scope, out-of-scope, Done when, Exit). "
            "When Done when is met, write a short outcome message for the user, then "
            f'call mark_task_completed(task_id="{tid}") and STOP. '
            f"{_LONG_OUTPUT_GUIDANCE}"
        )
    return (
        f"Retry plan task `{tid}` only. "
        "Complete the Done when criteria from the system-reminder before marking. "
        f"Do NOT call mark_task_completed unless the task is truly complete. "
        "When done, write a short outcome message for the user, then "
        f'call mark_task_completed(task_id="{tid}") and STOP immediately. '
        "Reuse the files already written by the previous attempt instead of "
        f"starting over. {_LONG_OUTPUT_GUIDANCE}"
    )
