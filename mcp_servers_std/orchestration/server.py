"""
MCP opzionale (stdio): espone gli stessi tool dell’orchestrazione in-process.

Per HITL in UI Chainlit si consiglia il profilo **Orchestrator** con registry
``type: in_process`` (tool nel processo API così gli eventi SSE raggiungono la UI).

Con questo server stdio, l’approve via API funziona se Redis/LocalFallback è condiviso
con il processo che esegue ``draft_execution_plan``.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

from src.runtime.orchestration_tools import run_draft_execution_plan, run_mark_task_completed

mcp = FastMCP("AION Orchestration")


@mcp.tool()
async def draft_execution_plan(goal: str, tasks: str | list | None = None) -> str:
    sid = (os.environ.get("AION_CHAT_SESSION_ID") or "default").strip()
    uid = (os.environ.get("AION_CURRENT_USER_ID") or "default").strip()
    return await run_draft_execution_plan(goal, tasks, session_id=sid, user_id=uid)


@mcp.tool()
async def mark_task_completed(plan_id: str, task_id: str) -> str:
    sid = (os.environ.get("AION_CHAT_SESSION_ID") or "default").strip()
    uid = (os.environ.get("AION_CURRENT_USER_ID") or "default").strip()
    return await run_mark_task_completed(plan_id, task_id, session_id=sid, user_id=uid)


if __name__ == "__main__":
    mcp.run()
