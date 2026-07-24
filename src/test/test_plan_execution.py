"""Plan execution reminders and deliverable path inference."""

from src.a2a.plan_markdown import markdown_to_plan, plan_to_markdown
from src.a2a.protocol import ExecutionPlan, ExecutionTask
from src.runtime.plan_execution import (
    build_plan_execution_reminder,
    infer_deliverable_path,
    plan_exec_max_tool_calls,
)


def test_plan_to_markdown_no_profile_on_tasks():
    plan = ExecutionPlan(
        goal="Doc WWDC",
        tasks=[
            ExecutionTask(
                id="task_01", title="Research", description="", depends_on=[]
            ),
        ],
    )
    md = plan_to_markdown(plan)
    assert "(profile:" not in md
    assert "## Deliverable" in md
    assert "`task_01`" in md
    assert "(deps: none)" in md


def test_infer_deliverable_path_from_section():
    md = """## Goal
x
## Deliverable
`workspace/wwdc-2026-guide.md`
## Tasks
- [ ] `task_01` **A** (deps: none)
"""
    assert infer_deliverable_path(md) == "workspace/wwdc-2026-guide.md"


def test_build_plan_execution_reminder_mentions_edit():
    md = plan_to_markdown(
        ExecutionPlan(
            goal="Guide",
            tasks=[
                ExecutionTask(
                    id="task_01",
                    title="Outline",
                    description="Done when: outline file exists in workspace.",
                    depends_on=[],
                ),
                ExecutionTask(
                    id="task_02",
                    title="Write Siri section",
                    description="Edit deliverable only.",
                    depends_on=["task_01"],
                ),
            ],
        )
    )
    rem = build_plan_execution_reminder(
        plan_id="execution_plan_abcd", plan_markdown=md, next_task_id="task_01"
    )
    assert "task_02" in rem
    assert "Out of scope" in rem
    assert "Done when" in rem
    assert "outline file exists" in rem
    assert "sandbox_edit_workspace_file" in rem
    assert "mark_task_completed" in rem
    assert "STOP" in rem


def test_iter_pending_tasks_after():
    from src.runtime.plan_execution import iter_pending_tasks_after

    md = plan_to_markdown(
        ExecutionPlan(
            goal="G",
            tasks=[
                ExecutionTask(id="task_01", title="A", description="", depends_on=[]),
                ExecutionTask(id="task_02", title="B", description="", depends_on=[]),
                ExecutionTask(id="task_03", title="C", description="", depends_on=[]),
            ],
        )
    )
    later = iter_pending_tasks_after(md, "task_01")
    assert later == [("task_02", "B"), ("task_03", "C")]


def test_build_plan_execution_trigger_retry():
    from src.runtime.plan_execution import build_plan_execution_trigger

    t0 = build_plan_execution_trigger("task_01", attempt=0)
    t1 = build_plan_execution_trigger("task_01", attempt=1)
    assert "task_01" in t0
    assert "Done when" in t1
    assert "truly complete" in t1


def test_plan_exec_max_tool_calls_default():
    assert plan_exec_max_tool_calls() >= 4
    assert plan_exec_max_tool_calls() == 24


def test_markdown_roundtrip_without_profile():
    md = """## Goal
G
## Tasks
- [ ] `task_01` **A** (deps: none)
"""
    plan = markdown_to_plan(md)
    out = plan_to_markdown(plan)
    assert "(profile:" not in out
    assert plan.tasks[0].id == "task_01"
