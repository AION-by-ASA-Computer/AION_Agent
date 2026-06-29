import pytest

from src.a2a.protocol import ExecutionPlan, ExecutionTask, TaskStatus


def test_execution_plan_roundtrip():
    p = ExecutionPlan(
        goal="Obiettivo",
        tasks=[
            ExecutionTask(id="a", title="uno", description="d1", depends_on=[]),
            ExecutionTask(id="b", title="due", description="d2", depends_on=["a"]),
        ],
    )
    raw = p.model_dump_json()
    p2 = ExecutionPlan.model_validate_json(raw)
    assert p2.goal == p.goal
    assert len(p2.tasks) == 2
    assert p2.tasks[1].depends_on == ["a"]


def test_cycle_rejected():
    with pytest.raises(ValueError):
        ExecutionPlan(
            goal="g",
            tasks=[
                ExecutionTask(id="a", title="a", description="", depends_on=["b"]),
                ExecutionTask(id="b", title="b", description="", depends_on=["a"]),
            ],
        )


def test_from_goal_and_tasks_json_string():
    p = ExecutionPlan.from_goal_and_tasks(
        "goal",
        '[{"id":"x","title":"t","description":"d","depends_on":[]}]',
    )
    assert p.tasks[0].id == "x"


def test_task_status_enum():
    assert TaskStatus.PENDING.value == "pending"
