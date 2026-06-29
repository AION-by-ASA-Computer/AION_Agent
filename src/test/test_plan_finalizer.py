"""Tests for PlanFinalizer and PlanModeController."""
import pytest

from src.a2a.plan_markdown import markdown_to_plan
from src.runtime.plan_coercion import looks_like_chat_plan
from src.runtime.plan_engine import PlanFinalizer, PlanModeController, next_pending_task_id


WWDC_ITALIAN_PLAN = """# Piano: Documento Markdown — Novità Apple WWDC 2026

## Obiettivo
Produrre un documento markdown completo sulle novità WWDC 2026.

## Contesto
Ricerca web già effettuata; output in italiano per lettori non tecnici.

## Task
**task_01**: Raccogliere e validare fonti ufficiali Apple
**task_02**: Sintetizzare annunci keynote per piattaforma
**task_03**: Descrivere novità iOS 26
**task_04**: Descrivere novità macOS 26
**task_05**: Descrivere novità watchOS 26
**task_06**: Descrivere novità tvOS 26
**task_07**: Descrivere novità visionOS 26
**task_08**: Coprire Apple Intelligence e AI on-device
**task_09**: Coprire Xcode e strumenti sviluppo
**task_10**: Coprire privacy e sicurezza
**task_11**: Redigere sezione conclusioni
**task_12**: Revisione coerenza terminologia
**task_13**: Controllo link e riferimenti
**task_14**: Formattazione markdown finale
"""


@pytest.mark.anyio
async def test_plan_finalizer_wwdc_italian_coercion(monkeypatch):
    monkeypatch.setenv("AION_PLAN_FINALIZE_LLM", "0")
    assert looks_like_chat_plan(WWDC_ITALIAN_PLAN)
    result = await PlanFinalizer.finalize(WWDC_ITALIAN_PLAN, user_message="WWDC 2026 doc")
    assert result is not None
    assert result.source in ("coercion", "fallback")
    assert result.tasks_count >= 14
    plan = markdown_to_plan(result.markdown)
    assert len(plan.tasks) >= 14
    assert plan.tasks[0].id == "task_01"


@pytest.mark.anyio
async def test_plan_finalizer_no_junk_fallback_on_invalid_input(monkeypatch):
    monkeypatch.setenv("AION_PLAN_FINALIZE_LLM", "0")
    result = await PlanFinalizer.finalize(
        "Ciao, sto pensando al progetto.",
        user_message="test",
        plan_id="execution_plan_stable01",
    )
    assert result is None


@pytest.mark.anyio
async def test_plan_finalizer_reuses_turn_plan_id(monkeypatch):
    monkeypatch.setenv("AION_PLAN_FINALIZE_LLM", "0")
    result = await PlanFinalizer.finalize(
        WWDC_ITALIAN_PLAN,
        user_message="WWDC",
        plan_id="execution_plan_abc12345",
    )
    assert result is not None
    assert result.plan_id == "execution_plan_abc12345"


def test_plan_finalizer_timeout_env(monkeypatch):
    from src.runtime.plan_engine import plan_finalizer_timeout_sec

    monkeypatch.setenv("AION_PLAN_FINALIZER_TIMEOUT_SEC", "12")
    assert plan_finalizer_timeout_sec() == 12.0
    monkeypatch.setenv("AION_PLAN_FINALIZER_TIMEOUT_SEC", "999")
    assert plan_finalizer_timeout_sec() == 120.0


def test_plan_mode_controller_stable_plan_id():
    ctrl = PlanModeController(plan_id="execution_plan_turn1")
    assert ctrl.plan_id == "execution_plan_turn1"
    phase = ctrl.sse_phase("finalizing", message="test")
    assert phase["plan_id"] == "execution_plan_turn1"
    prog = ctrl.sse_progress("# plan", tasks_count=2, revision=1)
    assert prog["plan_id"] == "execution_plan_turn1"
    assert prog["revision"] == 1
    err = ctrl.sse_plan_error("failed")
    assert err["type"] == "plan_error"
    assert err["plan_id"] == "execution_plan_turn1"


@pytest.mark.anyio
async def test_plan_finalizer_llm_json_path(monkeypatch):
    monkeypatch.setenv("AION_PLAN_FINALIZE_LLM", "1")

    async def _fake_complete(messages, **kwargs):
        return """{"goal": "Test goal", "context": "ctx", "tasks": [
            {"id": "task_01", "title": "First", "depends_on": []},
            {"id": "task_02", "title": "Second", "depends_on": ["task_01"]}
        ]}"""

    monkeypatch.setattr("src.research.llm_bridge.complete_messages", _fake_complete)
    result = await PlanFinalizer.finalize("some draft", user_message="q")
    assert result is not None
    assert result.source == "llm_json"
    assert result.tasks_count == 2


def test_plan_mode_controller_research_budget():
    ctrl = PlanModeController()
    ctrl.budget = 2
    assert ctrl.on_research_tool_start("web_search")[0] is True
    assert ctrl.on_research_tool_start("web_search")[0] is True
    allowed, msg = ctrl.on_research_tool_start("web_search")
    assert allowed is False
    assert msg
    assert ctrl.budget_exhausted is True


def test_next_pending_task_id():
    md = """## Tasks
- [ ] `task_01` **A** (profile: -) (deps: none)
- [x] `task_02` **B** (profile: -) (deps: none)
- [ ] `task_03` **C** (profile: -) (deps: none)
"""
    assert next_pending_task_id(md) == "task_01"
    md2 = md.replace("[ ] `task_01`", "[x] `task_01`")
    assert next_pending_task_id(md2) == "task_03"
