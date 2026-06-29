"""Entry point unico per delega sub-agent (tool Haystack ``delegate_task`` e MCP ``delegate_to_subagent``)."""

from __future__ import annotations


async def delegate_to_subagent_async(
    *,
    subagent_profile: str,
    task: str,
    user_id: str,
    parent_session_id: str,
) -> str:
    from .subagent_orchestrator import run_subagent_task

    return await run_subagent_task(
        subagent_profile=subagent_profile,
        task=task,
        user_id=user_id,
        parent_conversation_id=parent_session_id,
    )
