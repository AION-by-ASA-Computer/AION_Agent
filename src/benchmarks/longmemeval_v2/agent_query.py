"""Agent-based QA for LongMemEval-V2 (Haystack + memory_recall)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from src.agent_pipeline import AgentPipeline
from src.main import get_agent

from .query import normalize_actual_answer


async def answer_question_with_agent(
    question: str,
    *,
    run_id: str,
    profile_name: str,
    project_slug: str,
    session_id: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, float, Dict[str, Any]]:
    """Run the real Haystack agent with Mnemos memory_recall bound to the benchmark scope."""
    _ = config
    from .ingest import eval_scope

    _, user_id = eval_scope(run_id=run_id, project_slug=project_slug)

    agent_instance, resolved_profile = await get_agent(
        profile_name,
        session_id=session_id,
        user_id=user_id,
        tenant_id=os.getenv("AION_DEFAULT_TENANT_ID", "benchmark"),
    )
    pipeline = AgentPipeline(
        agent_instance,
        session_id=session_id,
        profile_name=resolved_profile,
        user_id=user_id,
    )

    tool_trace: List[Dict[str, Any]] = []
    memory_recalls = 0
    raw_text = ""
    start = time.monotonic()

    async for chunk in pipeline.run_stream(question, sql_query_project=project_slug):
        ctype = chunk.get("type")
        if ctype == "tool_event":
            evt = chunk.get("event") or {}
            tool_trace.append(evt)
            if evt.get("name") == "memory_recall" and evt.get("type") == "tool_start":
                memory_recalls += 1
        elif ctype == "final":
            raw_text = str(chunk.get("text") or "")

    latency = time.monotonic() - start
    normalized = normalize_actual_answer(raw_text)
    qa_debug: Dict[str, Any] = {
        "mode": "agent",
        "profile": resolved_profile,
        "project_slug": project_slug,
        "user_id": user_id,
        "tenant_id": os.getenv("AION_DEFAULT_TENANT_ID", "benchmark"),
        "memory_recall_calls": memory_recalls,
        "tool_trace": tool_trace,
        "raw_text": raw_text,
        "normalized_answer": normalized,
        "latency_sec": latency,
    }
    return normalized, latency, qa_debug
