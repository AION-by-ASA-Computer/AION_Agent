"""Unified pre_turn READ orchestrator for datasource memory (SQL cache + nav + project + session)."""

from __future__ import annotations

import logging
import os

from src.runtime.datasource_memory_mode import datasource_orchestrator_enabled
from src.runtime.hooks import HookContext, hook_registry
from src.runtime.query_memory_hooks import profile_wants_sql_query_memory_by_slug

logger = logging.getLogger("aion.datasource_memory.orchestrator")


async def _pre_turn_datasource_memory_orchestrator(ctx: HookContext) -> None:
    if not datasource_orchestrator_enabled():
        return
    profile = ctx.profile or ""
    if not profile_wants_sql_query_memory_by_slug(profile):
        return

    from src.runtime import query_memory_hooks

    await query_memory_hooks._run_pre_turn_sql_query_memory(ctx)

    mod_early = ctx.modified_payload or {}
    cache_hit = bool(mod_early.get("sql_query_memory_cache_hit"))
    user_input = (ctx.payload.get("user_input") or "").strip()

    project = (
        ctx.payload.get("sql_query_project")
        or os.getenv("AION_SQL_QM_DEFAULT_PROJECT")
        or "default"
    ).strip()

    try:
        from src.memory.mnemos.scope import sanitize_project_slug

        slug = sanitize_project_slug(project)
        if slug and slug != "default" and len((user_input or "").strip()) > 0:
            proj_ctx = f"ACTIVE_PROJECT: {slug}"
            merged = dict(ctx.modified_payload or ctx.payload)
            existing = (merged.get("project_context_inject") or "").strip()
            merged["project_context_inject"] = (
                (existing + "\n\n" + proj_ctx).strip() if existing else proj_ctx
            )
            ctx.modified_payload = merged
    except Exception as exc:
        logger.debug("project_context inject skipped: %s", exc)

    try:
        from src.runtime.datasource_turn_reminders import (
            should_skip_session_entity_cache,
        )
        from src.runtime.sql_query_memory_context import (
            format_session_entity_cache_block,
        )

        if not should_skip_session_entity_cache(
            user_input=user_input, cache_hit=cache_hit
        ):
            session_block = format_session_entity_cache_block(ctx.conversation_id)
            if session_block:
                merged = dict(ctx.modified_payload or ctx.payload)
                merged["session_entity_cache_inject"] = session_block
                ctx.modified_payload = merged
    except Exception as exc:
        logger.debug("session entity cache inject skipped: %s", exc)

    try:
        from src.runtime.datasource_turn_reminders import build_turn_state_reminder
        from src.runtime.exploration_tracker import needs_persist_reminder

        merged = dict(ctx.modified_payload or ctx.payload)
        reminder = build_turn_state_reminder(
            cache_hit=bool(merged.get("sql_query_memory_cache_hit")),
            has_sql_inject=bool((merged.get("sql_query_memory_inject") or "").strip()),
            needs_persist=needs_persist_reminder(ctx.conversation_id),
            user_input=user_input,
        )
        if reminder:
            existing = (merged.get("turn_state_reminder") or "").strip()
            merged["turn_state_reminder"] = (
                (existing + "\n\n" + reminder).strip() if existing else reminder
            )
            ctx.modified_payload = merged
    except Exception as exc:
        logger.debug("turn state reminder skipped: %s", exc)


def register_datasource_memory_orchestrator_hooks() -> None:
    hook_registry.register(
        "pre_turn", _pre_turn_datasource_memory_orchestrator, priority=25
    )


register_datasource_memory_orchestrator_hooks()
