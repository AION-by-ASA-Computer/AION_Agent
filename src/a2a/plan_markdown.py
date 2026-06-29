"""Markdown source-of-truth helpers for orchestration plans."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .protocol import ExecutionPlan, ExecutionTask

_PLAN_OPEN_RE = re.compile(r"^<plan\b[^>]*>", re.IGNORECASE)
_PLAN_CLOSE_RE = re.compile(r"</plan>\s*$", re.IGNORECASE)


def _unwrap_plan_xml_fence(markdown: str) -> str:
    """Rimuove opzionalmente il wrapper `<plan>...</plan>` (anche con attributi) così il parser vede ## Goal / ## Tasks."""
    s = (markdown or "").strip()
    m = _PLAN_OPEN_RE.match(s)
    if m:
        s = s[m.end() :].lstrip()
    if _PLAN_CLOSE_RE.search(s):
        i = s.lower().rfind("</plan>")
        if i >= 0:
            s = s[:i].rstrip()
    return s


# Regex per la linea base della task: id + titolo + metadati opzionali tra parentesi (ordine libero)
_TASK_LINE = re.compile(
    r"^\s*-\s*\[[ xX]\]\s*`(?P<id>[^`]+)`\s*\*\*(?P<title>[^*]+)\*\*"
    r"(?P<meta>(?:\s*\([^)]+\))*)\s*$"
)
# Estrazione dei singoli metadati dalle parentesi (order-independent)
_PROFILE_META = re.compile(r"\(profile:\s*([^)]+)\)")
_DEPS_META = re.compile(r"\(deps:\s*([^)]+)\)")
# Regex per toggle checkbox (solo id, ignora il resto)
_TASK_CHECK_LINE = re.compile(r"^(\s*-\s*\[)([ xX])(\]\s*`(?P<id>[^`]+)`.*)$")
# `- [ ] task_01: Title` (common Plan Mode / sidebar block editor output)
_TASK_COLON_ID = re.compile(
    r"^\s*-\s*\[(?P<checked>[ xX])\]\s*`?(?P<id>task_\d+)`?\s*:\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
# `- [ ] **task_01**: Title` (sidebar block editor when id is bold, not backtick)
_TASK_CHECKBOX_BOLD_ID = re.compile(
    r"^\s*-\s*\[(?P<checked>[ xX])\]\s*\*\*(?:`(?P<id>task_\d+)`|(?P<id2>task_\d+))\*\*\s*:?\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
# `task_01: Title` without checkbox (text block under ## Tasks in sidebar)
_TASK_PLAIN_COLON = re.compile(
    r"^\s*`?(?P<id>task_\d+)`?\s*:\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
# Fallback: checkbox senza backtick id (formato legacy Plan Mode prompt)
_TASK_LOOSE = re.compile(
    r"^\s*-\s*\[[ xX]\]\s*(?:\*\*)?"
    r"(?:(?:Task\s*)?(?P<num>\d+)|`?(?P<tid>task_\d+)`?)"
    r"\s*[:—\-–]\s*"
    r"(?:\*\*)?(?P<title>.+?)(?:\*\*)?\s*$",
    re.IGNORECASE,
)
_TASK_BOLD_ID = re.compile(
    r"^\s*\*\*(?:`(?P<id>task_\d+)`|(?P<id2>task_\d+))\*\*\s*:?\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
# Any checkbox line under ## Tasks (sidebar block editor often omits backtick ids)
_ORPHAN_CHECKBOX = re.compile(r"^\s*-\s*\[(?P<checked>[ xX])\]\s*(?P<body>.+?)\s*$")
_TASK_META_SUFFIX = re.compile(
    r"\s*\((?:deps|profile):\s*[^)]+\)\s*$",
    re.IGNORECASE,
)
_SECTION_ALIASES = {
    "## obiettivo": "goal",
    "## goal": "goal",
    "## tasks": "tasks",
    "## task": "tasks",
    "## compiti": "tasks",
    "## passi": "tasks",
    "## steps": "tasks",
    "## step": "tasks",
    "## tareas": "tasks",
    "## aufgaben": "tasks",
    "## tâches": "tasks",
    "## contesto": "context",
    "## context": "context",
    "## notes": "notes",
    "## note": "notes",
    "## deliverable": "deliverable",
}
_PLAIN_BULLET_TASK = re.compile(r"^\s*-\s+(?!\[[ xX]\])(.+?)\s*$")


def _normalize_section_header(line: str) -> str:
    ls = line.strip().lower()
    return _SECTION_ALIASES.get(ls, ls)


def _plain_bullet_title(line: str) -> str:
    """Strip list marker and light markdown from a plain ``- item`` task line."""
    m = _PLAIN_BULLET_TASK.match((line or "").rstrip())
    if not m:
        return ""
    title = (m.group(1) or "").strip()
    title = re.sub(r"^\*\*([^*]+)\*\*\s*:?\s*", r"\1", title)
    title = re.sub(r"^`([^`]+)`\s*", r"\1", title)
    return title.strip()


def _append_plain_bullet_task(
    out: List[ExecutionTask],
    line: str,
    *,
    min_title_len: int = 2,
) -> bool:
    title = _plain_bullet_title(line)
    if not title or len(title) < min_title_len:
        return False
    tid = f"task_{len(out) + 1:02d}"
    out.append(
        ExecutionTask(
            id=tid,
            title=title[:240],
            description="",
            depends_on=[],
            target_profile=None,
        )
    )
    return True


def _parse_loose_tasks_anywhere(lines: List[str]) -> List[ExecutionTask]:
    """Parse Task N — / checkbox / plain bullet lines when ## Tasks section is missing."""
    out: List[ExecutionTask] = []
    task_num = re.compile(
        r"^\s*(?:\*\*)?(?:Task\s*)(\d+)\s*[—\-–:]\s*(.+?)(?:\*\*)?\s*$",
        re.IGNORECASE,
    )
    for raw in lines:
        line = raw.rstrip()
        parsed = parse_task_checkbox_line(line)
        if parsed:
            tid, title, _done = parsed
            if title and len(title) >= 2:
                out.append(
                    ExecutionTask(
                        id=tid,
                        title=title[:240],
                        description="",
                        depends_on=[],
                        target_profile=None,
                    )
                )
            continue
        if _append_plain_bullet_task(out, line):
            continue
        m = task_num.match(line.strip())
        if not m:
            continue
        num = (m.group(1) or str(len(out) + 1)).strip()
        title = (m.group(2) or "").strip()
        if not title or len(title) < 2:
            continue
        tid = f"task_{num.zfill(2)}" if num.isdigit() else f"task_{len(out) + 1:02d}"
        out.append(
            ExecutionTask(
                id=tid,
                title=title[:240],
                description="",
                depends_on=[],
                target_profile=None,
            )
        )
    return out


def format_task_line(task: ExecutionTask, *, checked: bool = False) -> str:
    """Canonical task checkbox line (no per-task profile — unused in single-agent execution)."""
    deps = ", ".join(task.depends_on) if task.depends_on else "none"
    box = "x" if checked else " "
    return f"- [{box}] `{task.id}` **{task.title}** (deps: {deps})"


def parse_task_checkbox_line(line: str) -> Optional[Tuple[str, str, bool]]:
    """Parse a task checkbox line → (task_id, title, is_done), or None."""
    raw = (line or "").rstrip()
    if not raw.strip():
        return None
    m = _TASK_LINE.match(raw)
    if m:
        box_m = re.match(r"^\s*-\s*\[(?P<c>[ xX])\]", raw)
        checked = bool(box_m and box_m.group("c").strip().lower() == "x")
        return (m.group("id").strip(), m.group("title").strip(), checked)
    cm = _TASK_COLON_ID.match(raw.strip())
    if cm:
        done = cm.group("checked").strip().lower() == "x"
        return (cm.group("id").strip(), cm.group("title").strip(), done)
    bm = _TASK_CHECKBOX_BOLD_ID.match(raw.strip())
    if bm:
        done = bm.group("checked").strip().lower() == "x"
        tid = (bm.group("id") or bm.group("id2") or "").strip()
        title = (bm.group("title") or "").strip()
        if tid and title:
            return (tid, title, done)
    lm = _TASK_LOOSE.match(raw)
    if lm:
        box_m = re.match(r"^\s*-\s*\[(?P<c>[ xX])\]", raw)
        checked = bool(box_m and box_m.group("c").strip().lower() == "x")
        tid = (lm.group("tid") or "").strip()
        num = (lm.group("num") or "").strip()
        if not tid:
            tid = f"task_{num.zfill(2)}" if num.isdigit() else f"task_{1:02d}"
        title = (lm.group("title") or "").strip()
        if title:
            return (tid, title, checked)
    return None


def _canonical_task_id(index: int) -> str:
    return f"task_{max(1, index):02d}"


def is_degenerate_plan_json(plan_json: Optional[Dict[str, Any]]) -> bool:
    """True for parse-failure placeholders (single ``main`` task with a random uuid id)."""
    if not isinstance(plan_json, dict):
        return False
    tasks = plan_json.get("tasks") or []
    if len(tasks) != 1 or not isinstance(tasks[0], dict):
        return False
    t = tasks[0]
    title = str(t.get("title") or "").strip().lower()
    tid = str(t.get("id") or "").strip()
    if title == "main" and not re.match(r"^task_\d+$", tid, re.IGNORECASE):
        return True
    return False


def parse_orphan_task_checkbox_line(
    line: str,
    *,
    index: int,
) -> Optional[Tuple[str, str, bool]]:
    """Parse any ``- [ ] …`` line; assign ``task_NN`` when id is missing (sidebar free text)."""
    raw = (line or "").rstrip()
    if not raw:
        return None
    parsed = parse_task_checkbox_line(raw)
    if parsed:
        tid, title, checked = parsed
        if re.match(r"^task_\d+$", tid, re.IGNORECASE):
            return parsed
        return (_canonical_task_id(index), title, checked)
    m = _ORPHAN_CHECKBOX.match(raw)
    if not m:
        return None
    checked = m.group("checked").strip().lower() == "x"
    body = _TASK_META_SUFFIX.sub("", (m.group("body") or "").strip()).strip()
    if not body or len(body) < 2:
        return None
    idm = re.match(r"^`([^`]+)`\s*(.*)$", body)
    if idm:
        tid = idm.group(1).strip()
        rest = (idm.group(2) or "").strip()
        tm = re.search(r"\*\*([^*]+)\*\*", rest)
        title = (tm.group(1) if tm else rest).strip()
        if title:
            if not re.match(r"^task_\d+$", tid, re.IGNORECASE):
                tid = _canonical_task_id(index)
            return (tid, title[:240], checked)
    bold_m = re.match(r"^\*\*([^*]+)\*\*\s*:?\s*(.*)$", body)
    if bold_m:
        first = bold_m.group(1).strip()
        second = (bold_m.group(2) or "").strip()
        if re.match(r"^task_\d+$", first, re.IGNORECASE):
            title = second or first
            return (first, title[:240], checked)
        return (_canonical_task_id(index), first[:240], checked)
    return (_canonical_task_id(index), body[:240], checked)


def parse_task_plain_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse `task_01: Title` without checkbox prefix."""
    raw = (line or "").strip()
    if not raw or raw.startswith("#") or raw.startswith("- "):
        return None
    bold_m = _TASK_BOLD_ID.match(raw)
    if bold_m:
        tid = (bold_m.group("id") or bold_m.group("id2") or "").strip()
        title = (bold_m.group("title") or "").strip()
        if tid and title:
            return (tid, title)
    pm = _TASK_PLAIN_COLON.match(raw)
    if pm:
        tid = pm.group("id").strip()
        title = pm.group("title").strip()
        if tid and title:
            return (tid, title)
    return None


def iter_plan_task_rows(markdown: str) -> List[Tuple[str, str, bool]]:
    """All task lines in markdown: (task_id, title, is_done)."""
    rows: List[Tuple[str, str, bool]] = []
    in_tasks = False
    task_idx = 0
    for raw in _unwrap_plan_xml_fence(markdown or "").splitlines():
        line = raw.rstrip()
        section = _normalize_section_header(line.strip())
        if section == "tasks":
            in_tasks = True
            continue
        if line.strip().startswith("## ") and in_tasks:
            in_tasks = False
            continue
        if not in_tasks:
            continue
        task_idx += 1
        parsed = parse_task_checkbox_line(line)
        if not parsed:
            parsed = parse_orphan_task_checkbox_line(line, index=task_idx)
        if parsed:
            rows.append(parsed)
            continue
        plain = parse_task_plain_line(line)
        if plain:
            rows.append((plain[0], plain[1], False))
    return rows


def normalize_plan_task_lines(markdown: str) -> str:
    """Rewrite ## Tasks checkbox lines to canonical `- [ ] `task_XX` **Title**` format."""
    lines = _unwrap_plan_xml_fence(markdown or "").splitlines()
    out: List[str] = []
    in_tasks = False
    task_idx = 0
    for raw in lines:
        line = raw.rstrip()
        section = _normalize_section_header(line.strip())
        if section == "tasks":
            in_tasks = True
            out.append(line)
            continue
        if line.strip().startswith("## ") and in_tasks:
            in_tasks = False
        if in_tasks:
            task_idx += 1
            parsed = parse_task_checkbox_line(line)
            if not parsed:
                parsed = parse_orphan_task_checkbox_line(line, index=task_idx)
            if parsed:
                tid, title, done = parsed
                out.append(
                    format_task_line(
                        ExecutionTask(
                            id=tid,
                            title=title[:240],
                            description="",
                            depends_on=[],
                            target_profile=None,
                        ),
                        checked=done,
                    )
                )
                continue
            plain = parse_task_plain_line(line)
            if plain:
                tid, title = plain
                out.append(
                    format_task_line(
                        ExecutionTask(
                            id=tid,
                            title=title[:240],
                            description="",
                            depends_on=[],
                            target_profile=None,
                        ),
                        checked=False,
                    )
                )
                continue
        out.append(line)
    return "\n".join(out)


def plan_to_markdown(plan: ExecutionPlan) -> str:
    lines: List[str] = []
    lines.append("# Execution Plan")
    lines.append("")
    lines.append("## Goal")
    lines.append(plan.goal.strip())
    lines.append("")
    lines.append("## Context")
    lines.append(
        "_Contesto, vincoli e note di sfondo (markdown consentito). Modifica qui le spiegazioni lunghe._"
    )
    lines.append("")
    lines.append("## Deliverable")
    lines.append(
        "_Percorso file unico del documento finale, es. `workspace/progetto.md` — tutte le task di scrittura usano `sandbox_edit_workspace_file` dopo la prima._"
    )
    lines.append("")
    lines.append("## Tasks")
    for t in plan.tasks:
        lines.append(format_task_line(t))
        desc = (t.description or "").strip()
        if desc:
            lines.append(f"  - Description: {desc}")
    lines.append("")
    lines.append("## Notes")
    lines.append("- Annotazioni e modifiche prima dell'approvazione.")
    return "\n".join(lines)


def markdown_to_plan(markdown: str) -> ExecutionPlan:
    goal = ""
    tasks: List[ExecutionTask] = []
    lines = _unwrap_plan_xml_fence(markdown).splitlines()
    mode = ""
    pending_desc: Dict[str, str] = {}
    task_line_idx = 0
    for raw in lines:
        line = raw.rstrip()
        section = _normalize_section_header(line.strip())
        if section == "goal":
            mode = "goal"
            continue
        if section == "tasks":
            mode = "tasks"
            continue
        if section == "context":
            mode = "context"
            continue
        if section == "notes":
            mode = "notes"
            continue
        if section == "deliverable":
            mode = "deliverable"
            continue
        if line.strip().startswith("## "):
            mode = ""
            continue
        if mode == "goal":
            if line.strip():
                goal = (goal + " " + line.strip()).strip() if goal else line.strip()
            continue
        if mode in ("context", "notes", "deliverable"):
            continue
        if mode != "tasks":
            continue
        if not line.strip():
            continue
        m = _TASK_LINE.match(line)
        if m:
            # Estrai metadati order-independent dalle parentesi
            meta_str = m.group("meta") or ""
            pm = _PROFILE_META.search(meta_str)
            dm = _DEPS_META.search(meta_str)
            deps_raw = dm.group(1).strip() if dm else ""
            deps = []
            deps_token = deps_raw.lower()
            if deps_raw and deps_token not in ("-", "none", "nessuna", "null", "n/a"):
                deps = [x.strip() for x in deps_raw.split(",") if x.strip()]
            profile = pm.group(1).strip() if pm else ""
            if not profile or profile == "-":
                profile = None
            tid = m.group("id").strip()
            t = ExecutionTask(
                id=tid,
                title=m.group("title").strip(),
                description="",
                depends_on=deps,
                target_profile=profile,
            )
            tasks.append(t)
            pending_desc[tid] = ""
            continue
        if line.strip().startswith("- Description:") and tasks:
            desc = line.split(":", 1)[1].strip()
            pending_desc[tasks[-1].id] = desc
            continue
        parsed_cb = parse_task_checkbox_line(line)
        if parsed_cb:
            tid, title, _done = parsed_cb
            tasks.append(
                ExecutionTask(
                    id=tid,
                    title=title,
                    description="",
                    depends_on=[],
                    target_profile=None,
                )
            )
            pending_desc[tid] = ""
            continue
        plain = parse_task_plain_line(line)
        if plain:
            tid, title = plain
            tasks.append(
                ExecutionTask(
                    id=tid,
                    title=title,
                    description="",
                    depends_on=[],
                    target_profile=None,
                )
            )
            pending_desc[tid] = ""
            continue
        bold_m = _TASK_BOLD_ID.match(line.strip())
        if bold_m:
            tid = (bold_m.group("id") or bold_m.group("id2") or "").strip()
            title = (bold_m.group("title") or "").strip()
            if tid and title:
                tasks.append(
                    ExecutionTask(
                        id=tid,
                        title=title,
                        description="",
                        depends_on=[],
                        target_profile=None,
                    )
                )
                pending_desc[tid] = ""
                continue
        lm = _TASK_LOOSE.match(line)
        if lm:
            num = (lm.group("num") or str(len(tasks) + 1)).strip()
            title = (lm.group("title") or "").strip()
            tid = (lm.group("tid") or "").strip()
            if not tid:
                tid = (
                    f"task_{num.zfill(2)}"
                    if num.isdigit()
                    else f"task_{len(tasks) + 1:02d}"
                )
            if title:
                tasks.append(
                    ExecutionTask(
                        id=tid,
                        title=title,
                        description="",
                        depends_on=[],
                        target_profile=None,
                    )
                )
                pending_desc[tid] = ""
            continue
        task_line_idx += 1
        orphan = parse_orphan_task_checkbox_line(line, index=task_line_idx)
        if orphan:
            tid, title, _done = orphan
            tasks.append(
                ExecutionTask(
                    id=tid,
                    title=title,
                    description="",
                    depends_on=[],
                    target_profile=None,
                )
            )
            pending_desc[tid] = ""
            continue
        if _append_plain_bullet_task(tasks, line):
            pending_desc[tasks[-1].id] = ""

    if not goal:
        goal = "Execution plan"
    if not tasks:
        tasks = _parse_loose_tasks_anywhere(lines)
    if not tasks:
        raise ValueError("Nessun task trovato in markdown (sezione '## Tasks').")
    hydrated: List[ExecutionTask] = []
    for t in tasks:
        hydrated.append(
            ExecutionTask(
                id=t.id,
                title=t.title,
                description=pending_desc.get(t.id, "") or t.description,
                depends_on=t.depends_on,
                target_profile=t.target_profile,
            )
        )
    return ExecutionPlan(goal=goal, tasks=hydrated)


def plan_to_todos(plan: ExecutionPlan) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in plan.tasks:
        out.append(
            {
                "id": t.id,
                "title": t.title,
                "description": t.description or "",
                "status": str(
                    t.status.value if hasattr(t.status, "value") else t.status
                ),
                "depends_on": list(t.depends_on or []),
                "target_profile": t.target_profile or "",
                "comment": "",
            }
        )
    return out


def markdown_goal(markdown: str) -> str:
    goal = ""
    mode = ""
    for raw in _unwrap_plan_xml_fence(markdown).splitlines():
        line = raw.rstrip()
        if line.strip().lower() == "## goal":
            mode = "goal"
            continue
        if line.strip().startswith("## "):
            mode = ""
            continue
        if mode == "goal" and line.strip():
            goal = (goal + " " + line.strip()).strip() if goal else line.strip()
    return goal or "Execution plan"


def todos_to_plan(goal: str, todos: List[Dict[str, Any]]) -> ExecutionPlan:
    tasks: List[ExecutionTask] = []
    for i, t in enumerate(todos or []):
        if not isinstance(t, dict):
            raise ValueError(f"todo[{i}] non valido")
        tasks.append(
            ExecutionTask(
                id=str(t.get("id") or f"task_{i + 1}").strip(),
                title=str(t.get("title") or f"Task {i + 1}").strip(),
                description=str(t.get("description") or "").strip(),
                depends_on=[
                    str(x).strip()
                    for x in (t.get("depends_on") or [])
                    if str(x).strip()
                ],
                target_profile=(str(t.get("target_profile") or "").strip() or None),
                status=str(t.get("status") or "pending"),
            )
        )
    if not tasks:
        raise ValueError("todos vuoto")
    return ExecutionPlan(goal=goal, tasks=tasks)


def resolve_plan_markdown_for_approval(
    markdown: str,
    *,
    todos: Optional[List[Dict[str, Any]]] = None,
    plan_json: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ExecutionPlan]:
    """
    Parse sidebar/LLM plan markdown for approval.
    Coerces legacy formats and falls back to todos / plan JSON when needed.
    """
    from src.runtime.plan_coercion import coerce_chat_plan_to_canonical_markdown

    md = (markdown or "").strip()
    if todos and isinstance(todos, list) and len(todos) > 0:
        try:
            plan = todos_to_plan(markdown_goal(md) if md else "Execution plan", todos)
            return plan_to_markdown(plan), plan
        except Exception:
            pass

    candidates: List[str] = []
    if md:
        candidates.append(normalize_plan_task_lines(md))
        candidates.append(md)
    coerced = coerce_chat_plan_to_canonical_markdown(md) if md else None
    if coerced:
        candidates.append(normalize_plan_task_lines(coerced))

    seen: set[str] = set()
    for cand in candidates:
        key = cand.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            plan = markdown_to_plan(cand)
            return normalize_plan_task_lines(cand), plan
        except Exception:
            continue

    if (
        isinstance(plan_json, dict)
        and plan_json.get("tasks")
        and not is_degenerate_plan_json(plan_json)
    ):
        plan = ExecutionPlan.model_validate(plan_json)
        return plan_to_markdown(plan), plan

    raise ValueError("Nessun task trovato in markdown (sezione '## Tasks').")


def resolve_plan_markdown_lenient(
    markdown: str,
    *,
    todos: Optional[List[Dict[str, Any]]] = None,
    plan_json: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ExecutionPlan]:
    """Like resolve_plan_markdown_for_approval but never raises (approve / recovery path)."""
    try:
        return resolve_plan_markdown_for_approval(
            markdown,
            todos=todos,
            plan_json=plan_json,
        )
    except ValueError:
        pass
    md = (markdown or "").strip()
    goal = markdown_goal(md) or "Execution plan"
    loose = _parse_loose_tasks_anywhere(_unwrap_plan_xml_fence(md).splitlines())
    if loose:
        plan = ExecutionPlan(goal=goal, tasks=loose)
        return plan_to_markdown(plan), plan
    plan = ExecutionPlan.from_goal_and_tasks(goal, None)
    return plan_to_markdown(plan), plan


def normalize_approved_payload(payload: Any) -> Tuple[str, Dict[str, Any]]:
    """
    Accepts markdown string, legacy plan dict, or envelope dict.
    Returns (plan_markdown, metadata dict).
    """
    if isinstance(payload, str):
        md = payload.strip()
        if not md:
            raise ValueError("approved_markdown vuoto")
        return md, {}
    if isinstance(payload, dict):
        if isinstance(payload.get("plan_markdown"), str):
            md = payload["plan_markdown"].strip()
            meta = {
                "annotations": payload.get("annotations") or {},
                "todos": payload.get("todos") or [],
            }
            if not md:
                raise ValueError("plan_markdown vuoto")
            return md, meta
        # Legacy JSON plan
        plan = ExecutionPlan.model_validate(payload)
        return plan_to_markdown(plan), {}
    raise ValueError("Payload piano non supportato")


def mark_task_checked(markdown: str, task_id: str, checked: bool = True) -> str:
    """Toggle checkbox for a specific markdown task id (canonical or legacy formats)."""
    lines = _unwrap_plan_xml_fence(markdown).splitlines()
    target = (task_id or "").strip()
    if not target:
        raise ValueError("task_id vuoto")
    out: List[str] = []
    changed = False
    marker = "x" if checked else " "
    target_low = target.lower()
    for line in lines:
        parsed = parse_task_checkbox_line(line)
        plain = parse_task_plain_line(line) if not parsed else None
        if plain and plain[0].strip().lower() == target_low:
            out.append(
                format_task_line(
                    ExecutionTask(
                        id=plain[0],
                        title=plain[1][:240],
                        description="",
                        depends_on=[],
                        target_profile=None,
                    ),
                    checked=checked,
                )
            )
            changed = True
            continue
        if parsed and parsed[0].strip().lower() == target_low:
            tid, title, _ = parsed
            out.append(
                format_task_line(
                    ExecutionTask(
                        id=tid,
                        title=title[:240],
                        description="",
                        depends_on=[],
                        target_profile=None,
                    ),
                    checked=checked,
                )
            )
            changed = True
            continue
        m = _TASK_CHECK_LINE.match(line)
        if m and (m.group("id") or "").strip().lower() == target_low:
            out.append(f"{m.group(1)}{marker}{m.group(3)}")
            changed = True
            continue
        out.append(line)
    if not changed:
        raise ValueError(
            f"Task `{task_id}` not found in markdown. "
            "Formati supportati: `- [ ] `task_01` **Title**` oppure `- [ ] task_01: Title`."
        )
    return "\n".join(out)
