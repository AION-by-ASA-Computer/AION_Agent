"""PlanModeController SSE and budget helpers."""
from src.runtime.plan_engine import PlanModeController


def test_plan_mode_controller_sse_phase():
    ctrl = PlanModeController()
    evt = ctrl.sse_phase("researching", message="Searching")
    assert evt["type"] == "plan_phase"
    assert evt["phase"] == "researching"
    assert evt["message"] == "Searching"


def test_plan_mode_controller_sse_progress():
    ctrl = PlanModeController()
    evt = ctrl.sse_progress("# Plan\n## Task\n**task_01**: Do thing", tasks_count=1)
    assert evt["type"] == "plan_progress"
    assert evt["tasks_count"] == 1
    assert "task_01" in evt["plan_markdown"]


def test_non_research_tools_not_counted():
    ctrl = PlanModeController()
    ctrl.budget = 2
    assert ctrl.on_research_tool_start("mark_task_completed")[0] is True
    assert ctrl.research_count == 0
