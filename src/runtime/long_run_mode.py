"""Long Run mode: Pi backend agent loop with relaxed turn budgets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import FrozenSet


def long_run_enabled() -> bool:
    return (os.getenv("AION_LONG_RUN_ENABLED") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


DEFAULT_LONG_RUN_BLOCKED_TOOLS: FrozenSet[str] = frozenset(
    {
        "draft_execution_plan",
        "get_execution_plan",
        "update_execution_plan",
        "mark_task_completed",
        "delegate_to_subagent",
        "trigger_research",
        "manage_research",
    }
)


def long_run_blocked_tool_names() -> set[str]:
    raw = (os.getenv("AION_LONG_RUN_BLOCKED_TOOLS") or "").strip()
    if raw:
        return {t.strip() for t in raw.split(",") if t.strip()}
    return set(DEFAULT_LONG_RUN_BLOCKED_TOOLS)


def build_long_run_system_prompt() -> str:
    return (
        "\n\n## LONG RUN MODE ACTIVE\n"
        "You are in **LONG RUN MODE** (Pi agent runtime). The user expects a "
        "complete deliverable in one turn — e.g. research, structured data, "
        "and files in the session workspace (Excel, CSV, reports).\n\n"
        "### Required flow\n"
        "1. Gather data with web tools when needed, but avoid endless search loops.\n"
        "2. After enough sources, **write intermediate results to the workspace** "
        "(JSON/CSV) before generating the final artifact.\n"
        "3. Use sandbox tools (`sandbox_run_python_file`, `sandbox_write_workspace_file`) "
        "to produce the deliverable.\n"
        "4. End with a short summary and the path(s) of generated files.\n\n"
        "### Tool discipline\n"
        "- Prefer `incremental_execution_protocol`: one slice at a time, persist, then continue.\n"
        "- Context compaction runs automatically; do not repeat full fetch dumps in prose.\n"
    )


@dataclass
class LongRunTurnBudget:
    turn_timeout: float
    max_tool_calls: int
    max_tool_events: int
    no_progress_timeout: float


def long_run_turn_budget() -> LongRunTurnBudget:
    return LongRunTurnBudget(
        turn_timeout=float(os.getenv("AION_LONG_RUN_TURN_TIMEOUT", "3600")),
        max_tool_calls=int(os.getenv("AION_LONG_RUN_TOOL_CALLS_MAX", "200")),
        max_tool_events=int(os.getenv("AION_LONG_RUN_TOOL_EVENTS_MAX", "300")),
        no_progress_timeout=float(
            os.getenv("AION_LONG_RUN_NO_PROGRESS_TIMEOUT_SEC", "600")
        ),
    )


def pi_worker_url() -> str:
    return (os.getenv("AION_PI_WORKER_URL") or "http://127.0.0.1:8791").rstrip("/")


def pi_worker_secret() -> str:
    return (os.getenv("AION_PI_WORKER_SECRET") or "").strip()


def pi_session_dir(session_id: str) -> str:
    from src.session_workspace import session_root

    return str(session_root(session_id) / ".pi")
