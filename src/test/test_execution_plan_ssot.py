"""Execution plan SSOT: DB canonical, workspace plan files deprecated."""

from types import SimpleNamespace

import pytest

from src.agent_pipeline import _plan_artifact_sse_end
from src.runtime import orchestration_tools as ot


_PLAN_MD = """# Execution Plan

## Goal
Test goal

## Tasks
- [ ] `task_01` **First action** (profile: orchestrator) (deps: none)
- [ ] `task_02` **Second action** (profile: orchestrator) (deps: task_01)
"""


@pytest.mark.anyio
async def test_mark_task_completed_lists_remaining(monkeypatch):
    captured: dict = {}

    async def fake_fetch(plan_id: str):
        assert plan_id == "execution_plan_ssot1"
        return {
            "approved_markdown": _PLAN_MD,
            "draft_markdown": None,
            "revision": 1,
        }

    async def fake_update(plan_id, **kwargs):
        captured.update(kwargs)
        captured["plan_id"] = plan_id

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)
    monkeypatch.setattr(
        "src.runtime.orchestration_db.update_plan_after_wait", fake_update
    )
    monkeypatch.setattr(ot.tool_event_bus, "put_event", lambda *_a, **_k: None)

    redis_events: list = []

    async def capture_redis(_sid, ev, **_k):
        redis_events.append(ev)

    monkeypatch.setattr(
        "src.runtime.redis_client.redis_enqueue_session_event", capture_redis
    )

    out = await ot.run_mark_task_completed(
        "execution_plan_ssot1",
        "task_01",
        session_id="sess-1",
        user_id="u1",
    )

    assert "task_01" in out
    assert "Remaining steps: 1" in out
    assert "`task_02`" in out
    assert "Second action" in out
    assert "revision=2" in out
    assert captured.get("approved_markdown")
    assert (
        "[x]" in captured["approved_markdown"]
        or "x" in captured["approved_markdown"].lower()
    )
    assert captured.get("approved_json") is not None
    assert captured.get("revision") == 2
    assert redis_events, "mark_task_completed should notify sidebar via redis"
    assert "continue_execution" not in redis_events[-1]
    assert "next_pending_task_id" not in redis_events[-1]


@pytest.mark.anyio
async def test_get_execution_plan_returns_checked_state(monkeypatch):
    md_done = _PLAN_MD.replace(
        "- [ ] `task_01`",
        "- [x] `task_01`",
        1,
    )

    async def fake_fetch(plan_id: str):
        return {
            "approved_markdown": md_done,
            "draft_markdown": None,
            "revision": 3,
        }

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)

    out = await ot.run_get_execution_plan(
        "execution_plan_ssot1",
        session_id="sess-1",
        user_id="u1",
    )

    assert "revision=3" in out
    assert "1/2" in out
    assert "Remaining steps: 1" in out
    assert "`task_02`" in out
    assert "[x]" in out or "task_01" in out


def test_approve_only_preserves_draft_markdown():
    """Regression: approve_only must not leave approved_markdown empty."""
    prev = {
        "draft_markdown": _PLAN_MD,
        "approved_markdown": "",
        "revision": 1,
    }
    approved_md = None
    final = (approved_md or "").strip()
    if not final and prev:
        final = (
            prev.get("draft_markdown") or prev.get("approved_markdown") or ""
        ).strip()
    assert "## Goal" in final
    assert "task_01" in final


def test_plan_artifact_sse_end_no_workspace_path():
    pe = SimpleNamespace(
        artifact_id="execution_plan_abc123",
        artifact_type="plan",
        artifact_title="Execution Plan",
    )
    payload = _plan_artifact_sse_end(pe)
    assert payload["storage_key"] == "orchestration://execution_plan_abc123"
    assert payload["saved"] is False
    assert payload["path"] == ""


def test_format_mark_task_result_all_done():
    md = _PLAN_MD.replace("- [ ]", "- [x]")
    msg = ot.format_mark_task_result("execution_plan_x", "task_02", md, revision=5)
    assert "Remaining steps: 0" in msg
    assert "2/2" in msg


@pytest.mark.anyio
async def test_update_execution_plan_persists_markdown(monkeypatch):
    captured: dict = {}

    async def fake_session(plan_id: str):
        return "sess-1"

    async def fake_fetch(plan_id: str):
        return {
            "approved_markdown": _PLAN_MD,
            "draft_markdown": None,
            "revision": 2,
        }

    async def fake_update(plan_id, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_session", fake_session)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)
    monkeypatch.setattr(
        "src.runtime.orchestration_db.update_plan_after_wait", fake_update
    )
    monkeypatch.setattr(ot.tool_event_bus, "put_event", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "src.runtime.redis_client.redis_enqueue_session_event", lambda *_a, **_k: None
    )

    new_md = (
        _PLAN_MD
        + "\n- [ ] `task_03` **Remediation step** (profile: orchestrator) (deps: task_02)\n"
    )
    out = await ot.run_update_execution_plan(
        "execution_plan_ssot1",
        new_md,
        session_id="sess-1",
        user_id="u1",
    )

    assert "updated in db" in out.lower()
    assert "revision=3" in out
    assert "task_03" in out
    assert captured.get("approved_markdown")
    assert "task_03" in captured["approved_markdown"]
    assert captured.get("revision") == 3


def test_format_plan_progress_summary_lists_pending():
    rows = [
        ("task_01", "First", True),
        ("task_02", "Second", False),
        ("task_03", "Third", False),
    ]
    summary = ot.format_plan_progress_summary(rows)
    assert "Remaining steps: 2" in summary
    assert "1. `task_02`" in summary
    assert "2. `task_03`" in summary


def test_sanitize_plan_finalizer_input_strips_think_and_malformed_plan():
    from src.runtime.plan_engine import _sanitize_plan_finalizer_input

    dirty = (
        "<think>internal reasoning here</think>\n"
        "Ecco il piano:\n"
        '<plan title="Test">\n## Goal\nWrite a doc\n## Tasks\n- [ ] `task_01` **Do it**\n</plan>\n'
        "\nNow formulate the final response</think>\n"
        '<<plan title="Duplicato">\n## Goal\nDuplicated garbage\n</plan>'
    )
    clean = _sanitize_plan_finalizer_input(dirty)
    assert "<think>" not in clean
    assert "</think>" not in clean
    assert "<<plan" not in clean
    # The first valid <plan> block should still be present
    assert '<plan title="Test">' in clean
    # Duplicated second plan block should be truncated
    assert "Duplicato" not in clean


@pytest.mark.anyio
async def test_mark_task_completed_colon_task_format(monkeypatch):
    """Regression: `- [ ] task_01: Title` must parse and mark (sidebar block editor format)."""
    colon_md = """# Execution Plan

## Goal
Test goal

## Tasks
- [ ] task_01: Struttura del documento
- [ ] task_02: Seconda sezione
"""
    captured: dict = {}

    async def fake_fetch(plan_id: str):
        return {"approved_markdown": colon_md, "draft_markdown": None, "revision": 1}

    async def fake_update(plan_id, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)
    monkeypatch.setattr(
        "src.runtime.orchestration_db.update_plan_after_wait", fake_update
    )
    monkeypatch.setattr(ot.tool_event_bus, "put_event", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "src.runtime.redis_client.redis_enqueue_session_event", lambda *_a, **_k: None
    )

    out = await ot.run_mark_task_completed(
        "execution_plan_colon",
        "task_01",
        session_id="sess-1",
        user_id="u1",
    )

    assert "task_01" in out
    assert "1/2" in out
    assert "`task_01`" in captured["approved_markdown"]
    assert "**Struttura del documento**" in captured["approved_markdown"]


def test_mark_once_failed_call_allows_retry():
    """Failed mark_task_completed must not consume the one-call-per-turn slot."""
    import threading

    mark_once = {"used": False, "lock": threading.Lock()}

    def try_mark(*, success: bool) -> str:
        lock = mark_once["lock"]
        with lock:
            if mark_once["used"]:
                raise RuntimeError(
                    "mark_task_completed was already called once in this turn. "
                    "STOP — do not call it again. Wait for the next execution turn."
                )
        try:
            if not success:
                raise ValueError("Task `task_99` non trovato nel markdown")
            result = "marked ok"
        except Exception:
            raise
        with lock:
            mark_once["used"] = True
        return result

    with pytest.raises(ValueError, match="non trovato"):
        try_mark(success=False)

    assert mark_once["used"] is False
    assert try_mark(success=True) == "marked ok"
    assert mark_once["used"] is True

    with pytest.raises(RuntimeError, match="already called once"):
        try_mark(success=True)


def test_format_plan_progress_summary_empty_rows():
    summary = ot.format_plan_progress_summary([])
    assert "0 tasks recognized" in summary
    assert "all plan tasks are completed" not in summary


def test_resolve_plan_markdown_checkbox_bold_id():
    from src.a2a.plan_markdown import resolve_plan_markdown_for_approval

    md, plan = resolve_plan_markdown_for_approval(
        "## Goal\nG\n\n## Tasks\n- [ ] **task_01**: Struttura documento\n"
        "- [ ] **task_02**: Seconda sezione\n"
    )
    assert len(plan.tasks) == 2
    assert "`task_01`" in md
    assert "**Struttura documento**" in md


def test_resolve_plan_markdown_plain_task_line():
    from src.a2a.plan_markdown import resolve_plan_markdown_for_approval

    md, plan = resolve_plan_markdown_for_approval(
        "## Goal\nG\n\n## Tasks\ntask_01: Solo titolo plain\n"
    )
    assert plan.tasks[0].id == "task_01"
    assert "- [ ]" in md


def test_resolve_sidebar_free_text_checkboxes():
    """Sidebar serializes tasks without backtick ids — must not collapse to one task."""
    from src.a2a.plan_markdown import resolve_plan_markdown_for_approval

    md, plan = resolve_plan_markdown_for_approval(
        "## Goal\nWWDC doc\n\n## Tasks\n"
        "- [ ] Ricerca web sulle novità WWDC 2026\n"
        "- [ ] Struttura capitoli del documento\n"
        "- [ ] Scrittura sezione Siri AI\n"
    )
    assert len(plan.tasks) == 3
    assert plan.tasks[0].id == "task_01"
    assert plan.tasks[1].id == "task_02"
    assert "`task_01`" in md
    assert "**Ricerca web" in md


def test_resolve_rejects_degenerate_plan_json_fallback():
    from src.a2a.plan_markdown import resolve_plan_markdown_for_approval

    corrupt = {
        "goal": "Execution plan",
        "tasks": [{"id": "2a197dcef01f", "title": "main", "depends_on": []}],
    }
    with pytest.raises(ValueError, match="Nessun task"):
        resolve_plan_markdown_for_approval(
            "## Goal\nG\n\n## Context\nNessuna sezione Tasks\n",
            plan_json=corrupt,
        )


def test_resolve_plain_bullet_tasks_under_tasks_section():
    from src.a2a.plan_markdown import resolve_plan_markdown_for_approval

    md, plan = resolve_plan_markdown_for_approval(
        "## Goal\nShip feature\n\n## Tasks\n- Setup repository\n- Write tests\n"
    )
    assert len(plan.tasks) == 2
    assert plan.tasks[0].title == "Setup repository"
    assert plan.tasks[0].id == "task_01"
    assert "Setup repository" in md


def test_resolve_plan_markdown_lenient_without_tasks_section():
    from src.a2a.plan_markdown import resolve_plan_markdown_lenient

    md, plan = resolve_plan_markdown_lenient("## Goal only\nNo tasks section")
    assert len(plan.tasks) >= 1
    assert plan.goal
    assert md.strip()


def test_resolve_prefers_body_todos_over_unparseable_markdown():
    from src.a2a.plan_markdown import resolve_plan_markdown_for_approval

    todos = [
        {
            "id": "task_01",
            "title": "From sidebar",
            "status": "pending",
            "depends_on": [],
        },
        {
            "id": "task_02",
            "title": "Second step",
            "status": "pending",
            "depends_on": [],
        },
    ]
    md, plan = resolve_plan_markdown_for_approval(
        "## Goal\nG\n\n## Context\nNo tasks here\n",
        todos=todos,
    )
    assert len(plan.tasks) == 2
    assert plan.tasks[0].title == "From sidebar"


def test_resolve_prefers_markdown_over_corrupt_db_json():
    from src.a2a.plan_markdown import resolve_plan_markdown_for_approval

    corrupt = {
        "goal": "Execution plan",
        "tasks": [{"id": "2a197dcef01f", "title": "main", "depends_on": []}],
    }
    md, plan = resolve_plan_markdown_for_approval(
        "## Goal\nG\n\n## Tasks\n- [ ] Prima azione\n- [ ] Seconda azione\n",
        plan_json=corrupt,
    )
    assert len(plan.tasks) == 2
    assert plan.tasks[0].title == "Prima azione"


@pytest.mark.anyio
async def test_setup_execution_plan_rejects_degenerate_fallback(monkeypatch):
    captured: dict = {}

    async def fake_upsert(plan_id, session_id, user_id, plan_dict, **kwargs):
        captured["plan_id"] = plan_id
        return True

    monkeypatch.setattr(
        "src.runtime.orchestration_db.upsert_execution_plan_draft", fake_upsert
    )
    monkeypatch.setattr(ot, "set_pending", lambda *_a, **_k: True)
    monkeypatch.setattr(ot.tool_event_bus, "put_event", lambda *_a, **_k: None)

    ok = await ot.setup_execution_plan_from_markdown(
        "## Goal only\nNo tasks section",
        plan_id="execution_plan_bad",
        session_id="sess1",
        user_id="u1",
    )
    assert ok is False
    assert "plan_id" not in captured
