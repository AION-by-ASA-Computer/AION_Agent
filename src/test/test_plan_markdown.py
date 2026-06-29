from src.a2a.plan_markdown import (
    mark_task_checked,
    markdown_goal,
    markdown_to_plan,
    normalize_approved_payload,
    plan_to_markdown,
    plan_to_todos,
    todos_to_plan,
)
from src.a2a.protocol import ExecutionPlan, ExecutionTask


def test_markdown_to_plan_italian_sections_and_bold_task_ids():
    md = """## Obiettivo
Obiettivo verificabile

## Contesto
Contesto di test

## Task
**task_01**: Prima azione
**task_02**: Seconda azione
"""
    plan = markdown_to_plan(md)
    assert plan.goal == "Obiettivo verificabile"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].id == "task_01"
    assert "Prima" in plan.tasks[0].title


def test_plan_markdown_roundtrip():
    plan = ExecutionPlan(
        goal="Write docs",
        tasks=[
            ExecutionTask(id="t1", title="Outline", description="Create structure", depends_on=[]),
            ExecutionTask(id="t2", title="Draft", description="Write pages", depends_on=["t1"], target_profile="planner"),
        ],
    )
    md = plan_to_markdown(plan)
    parsed = markdown_to_plan(md)
    assert parsed.goal == "Write docs"
    assert len(parsed.tasks) == 2
    assert parsed.tasks[1].depends_on == ["t1"]


def test_normalize_payload_markdown():
    md, meta = normalize_approved_payload(
        {
            "plan_markdown": "## Goal\nx\n## Tasks\n- [ ] `a` **A** (profile: -) (deps: -)",
            "annotations": {"a": "ok"},
            "todos": [{"id": "a", "title": "A", "status": "pending", "depends_on": [], "target_profile": ""}],
        }
    )
    assert "## Goal" in md
    assert meta.get("annotations", {}).get("a") == "ok"
    assert isinstance(meta.get("todos"), list)


def test_todos_conversion_roundtrip():
    plan = ExecutionPlan(
        goal="goal demo",
        tasks=[ExecutionTask(id="x1", title="Task 1", description="do", depends_on=[], target_profile="aion_std")],
    )
    todos = plan_to_todos(plan)
    rebuilt = todos_to_plan(markdown_goal(plan_to_markdown(plan)), todos)
    assert rebuilt.tasks[0].id == "x1"
    assert rebuilt.tasks[0].target_profile == "aion_std"


def test_markdown_context_and_notes_ignored_for_tasks():
    md = """# Execution Plan
## Goal
G main

## Context
Some *context* line must not become a task.

## Tasks
- [ ] `a` **Alpha** (profile: -) (deps: none)

## Notes
Freeform notes.
"""
    p = markdown_to_plan(md)
    assert p.goal == "G main"
    assert len(p.tasks) == 1
    assert p.tasks[0].id == "a"


def test_markdown_to_plan_strips_plan_xml_wrapper():
    md = """<plan>
# Execution Plan

## Goal
Test goal

## Tasks
- [ ] `t1` **One** (profile: orchestrator) (deps: none)
</plan>"""
    p = markdown_to_plan(md)
    assert p.goal == "Test goal"
    assert len(p.tasks) == 1
    assert p.tasks[0].id == "t1"


def test_markdown_to_plan_strips_plan_tag_with_title_attribute():
    md = """<plan title="Documento Markdown — Novità Apple WWDC 2026">
# Execution Plan

## Goal
Raccogliere le novità WWDC 2026

## Tasks
- [ ] `task_01` **Ricerca fonti ufficiali** (profile: -) (deps: none)
</plan>"""
    p = markdown_to_plan(md)
    assert "WWDC" in p.goal
    assert len(p.tasks) == 1
    assert p.tasks[0].id == "task_01"


def test_mark_task_checked():
    md = """# Plan
## Goal
Demo
## Tasks
- [ ] `t1` **Task 1** (profile: generic_assistant) (deps: none)
  - Description: first
- [ ] `t2` **Task 2** (profile: generic_assistant) (deps: t1)
  - Description: second
"""
    out = mark_task_checked(md, "t1", checked=True)
    assert "- [x] `t1`" in out
    assert "- [ ] `t2`" in out

