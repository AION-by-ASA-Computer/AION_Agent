"""Plan Mode research budget soft-block (agent must continue to draft_execution_plan)."""

import asyncio

from src.runtime.context import clear_context, set_context
from src.runtime.plan_engine import PlanModeController, block_plan_mode_research_tool


def test_block_plan_mode_research_tool_allows_up_to_budget():
    clear_context()
    ctrl = PlanModeController()
    ctrl.budget = 2
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    set_context("sess-budget", loop, queue, None, plan_controller=ctrl)

    assert block_plan_mode_research_tool("web_search") is None
    assert block_plan_mode_research_tool("web_search") is None
    assert ctrl.research_count == 2

    blocked = block_plan_mode_research_tool("skill_search")
    assert blocked is not None
    assert "draft_execution_plan" in blocked
    assert ctrl.budget_exhausted is True


def test_block_plan_mode_research_tool_ignores_non_research_tools():
    clear_context()
    ctrl = PlanModeController()
    ctrl.budget = 1
    set_context("sess-budget", None, None, None, plan_controller=ctrl)

    assert block_plan_mode_research_tool("draft_execution_plan") is None
    assert ctrl.research_count == 0

    clear_context()
