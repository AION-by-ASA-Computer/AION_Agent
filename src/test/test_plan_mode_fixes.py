"""Regression tests for Plan Mode prompt, tool blocking, parsing, and coercion."""
import os

import pytest

from src.a2a.plan_markdown import markdown_to_plan
from src.runtime.plan_coercion import (
    coerce_chat_plan_to_canonical_markdown,
    looks_like_chat_plan,
)
from src.runtime.plan_mode import (
    DEFAULT_PLAN_MODE_BLOCKED_TOOLS,
    DEFAULT_PLAN_MODE_RESEARCH_TOOLS,
    build_plan_mode_system_prompt,
    plan_mode_blocked_tool_names,
    plan_mode_max_research_tools,
    plan_mode_research_tool_names,
)


def test_plan_mode_blocked_tools_default_without_env(monkeypatch):
    monkeypatch.delenv("AION_PLAN_MODE_BLOCKED_TOOLS", raising=False)
    names = plan_mode_blocked_tool_names()
    assert names == set(DEFAULT_PLAN_MODE_BLOCKED_TOOLS)


def test_plan_mode_prompt_requires_tool_first_shape(monkeypatch):
    monkeypatch.setenv("AION_PLAN_MODE_TOOL_FIRST", "1")
    monkeypatch.setenv("AION_PLAN_TEXT_PARSER", "0")
    prompt = build_plan_mode_system_prompt()
    assert "draft_execution_plan" in prompt
    assert "PLAN MODE" in prompt
    assert "skill_view" in prompt
    assert "<plan" not in prompt


def test_plan_mode_guard_tool_first_allows_chat_without_plan_tag():
    from src.runtime.plan_mode_guard import plan_mode_response_valid

    ok, reason = plan_mode_response_valid(
        "Here is a short summary of the plan for your review.",
        plan_registered=False,
        tool_first=True,
    )
    assert ok is True
    assert reason == "ok_tool_first"


def test_plan_mode_guard_tool_first_blocks_deliverable_leak():
    from src.runtime.plan_mode_guard import plan_mode_response_valid

    ok, reason = plan_mode_response_valid(
        "```python\nfrom docx import Document\n```",
        plan_registered=False,
        tool_first=True,
    )
    assert ok is False
    assert reason == "deliverable_code_without_plan"


def test_plan_mode_prompt_legacy_text_parser(monkeypatch):
    monkeypatch.setenv("AION_PLAN_MODE_TOOL_FIRST", "0")
    prompt = build_plan_mode_system_prompt()
    assert "<plan" in prompt or "## Goal" in prompt


def test_plan_mode_draft_tool_not_blocked_by_default():
    assert "draft_execution_plan" not in DEFAULT_PLAN_MODE_BLOCKED_TOOLS
    assert "get_execution_plan" not in DEFAULT_PLAN_MODE_BLOCKED_TOOLS


def test_effective_blocked_tools_keeps_draft_when_tool_first(monkeypatch):
    from src.runtime.plan_mode import effective_plan_mode_blocked_tool_names

    monkeypatch.setenv("AION_PLAN_MODE_TOOL_FIRST", "1")
    monkeypatch.setenv(
        "AION_PLAN_MODE_BLOCKED_TOOLS",
        "draft_execution_plan,mark_task_completed,sandbox_write_workspace_file",
    )
    names = effective_plan_mode_blocked_tool_names()
    assert "draft_execution_plan" not in names
    assert "mark_task_completed" in names


def test_plan_mode_blocks_skill_view_by_default():
    assert "skill_view" in DEFAULT_PLAN_MODE_BLOCKED_TOOLS


def test_plan_mode_max_research_tools_default(monkeypatch):
    monkeypatch.delenv("AION_PLAN_MODE_MAX_RESEARCH_TOOLS", raising=False)
    assert plan_mode_max_research_tools() == 2


def test_plan_mode_research_tools_default_without_env(monkeypatch):
    monkeypatch.delenv("AION_PLAN_MODE_RESEARCH_TOOLS", raising=False)
    names = plan_mode_research_tool_names()
    assert names == set(DEFAULT_PLAN_MODE_RESEARCH_TOOLS)


def test_plan_mode_research_tools_from_env(monkeypatch):
    monkeypatch.setenv(
        "AION_PLAN_MODE_RESEARCH_TOOLS",
        "web_search,brave_search,sandbox_list_files",
    )
    names = plan_mode_research_tool_names()
    assert names == {"web_search", "brave_search", "sandbox_list_files"}


def test_plan_mode_prompt_lists_custom_research_tools(monkeypatch):
    monkeypatch.setenv("AION_PLAN_MODE_RESEARCH_TOOLS", "web_search,custom_mcp_search")
    prompt = build_plan_mode_system_prompt()
    assert "custom_mcp_search" in prompt
    assert "web_search" in prompt


def test_markdown_to_plan_loose_checkbox_inside_plan_tag():
    md = """<plan>
## Goal
Corso ML

## Tasks
- [ ] Task 1: Fondamenti statistici
- [ ] Task 2: Modelli classici
</plan>"""
    plan = markdown_to_plan(md)
    assert plan.goal == "Corso ML"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].id == "task_01"


def test_coerce_chat_plan_task_dash_format():
    chat = """Piano di Esecuzione: Corso ML Forecasting

Task 1 — Definizione syllabus e struttura capitoli
Task 2 — Ricerca web fonti tecniche
Task 3 — Scrittura modulo fondamenti
"""
    assert looks_like_chat_plan(chat)
    coerced = coerce_chat_plan_to_canonical_markdown(chat)
    assert coerced is not None
    assert coerced.strip().lower().startswith("<plan")
    plan = markdown_to_plan(coerced)
    assert len(plan.tasks) >= 3
    assert "syllabus" in plan.tasks[0].title.lower() or "Definizione" in plan.tasks[0].title


def test_coerce_structured_markdown_without_plan_wrapper():
    chat = """# Execution Plan

## Goal
Documentare novita WWDC 2026

## Tasks
- [ ] `task_01` **Raccogliere fonti ufficiali Apple** (profile: -) (deps: none)
- [ ] `task_02` **Scrivere sezioni per piattaforma** (profile: -) (deps: task_01)
"""
    assert looks_like_chat_plan(chat)
    coerced = coerce_chat_plan_to_canonical_markdown(chat)
    assert coerced is not None
    assert coerced.strip().lower().startswith("<plan")
    plan = markdown_to_plan(coerced)
    assert len(plan.tasks) == 2
    assert plan.tasks[0].id == "task_01"


def test_coerce_italian_task_bold_id_format():
    chat = """# Piano: Novità Apple WWDC 2026

## Obiettivo
Documentare le novità principali.

## Task
**task_01**: Raccogliere fonti ufficiali
**task_02**: Scrivere sezioni per piattaforma
"""
    assert looks_like_chat_plan(chat)
    coerced = coerce_chat_plan_to_canonical_markdown(chat)
    assert coerced is not None
    plan = markdown_to_plan(coerced)
    assert len(plan.tasks) == 2
    assert plan.tasks[0].id == "task_01"


def test_coerce_malformed_plan_title_prefix():
    chat = """plan title="Documento Markdown — Novita Apple WWDC 2026"
# Execution Plan
## Goal
Spiegare tutte le novita principali
## Tasks
- [ ] `task_01` **Raccolta annunci keynote** (profile: -) (deps: none)
- [ ] `task_02` **Stesura bozza finale** (profile: -) (deps: task_01)
"""
    assert looks_like_chat_plan(chat)
    coerced = coerce_chat_plan_to_canonical_markdown(chat)
    assert coerced is not None
    plan = markdown_to_plan(coerced)
    assert len(plan.tasks) == 2


@pytest.mark.anyio
async def test_plan_mode_tool_filtering_uses_defaults(monkeypatch, tmp_path):
    """Without AION_PLAN_MODE_BLOCKED_TOOLS in env, mutating tools are still removed."""
    from src.main import get_agent

    profiles_dir = tmp_path / "config" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "generic_assistant.yaml").write_text(
        """
name: Generic Assistant
description: test
instructions: test
skills:
  - core_protocol
mcp_servers: []
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.agent_profile.profile_manager.base_path", profiles_dir)
    from src.agent_profile import profile_manager

    profile_manager.load_all()
    async def _warm(*args, **kwargs):
        return None

    monkeypatch.setattr("src.main.mcp_manager.warm_session", _warm)
    monkeypatch.delenv("AION_PLAN_MODE_BLOCKED_TOOLS", raising=False)

    class FakeTool:
        def __init__(self, name: str):
            self.name = name

    fake_tools = [
        FakeTool("sandbox_write_workspace_file"),
        FakeTool("sandbox_list_files"),
    ]

    async def dummy_build(*args, **kwargs):
        return list(fake_tools)

    monkeypatch.setattr("src.main.build_all_tools", dummy_build)
    captured: list = []

    def mock_create_aion_agent(*, chat_generator, tools, system_prompt, **kwargs):
        captured.clear()
        captured.extend(tools)
        return object()

    monkeypatch.setattr("src.main.create_aion_agent", mock_create_aion_agent)
    monkeypatch.setattr("src.main._AGENT_CACHE_ENABLED", False)

    await get_agent(profile_name="generic_assistant", agent_mode="plan")
    names = {t.name for t in captured}
    assert "sandbox_write_workspace_file" not in names
    assert "sandbox_list_files" in names
