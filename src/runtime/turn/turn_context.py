"""TurnContext: pre-flight context prep extracted from AgentPipeline.run_stream.

Covers lines ~1192-1550 of agent_pipeline.py:
  - LTM wake-up
  - STM window fetch
  - User input augmentation (skill nudge, operational context, pre-turn hooks, LTM)
  - Message list assembly
  - Context compression / token budget truncation

Usage
-----
    buffered_sse: list[dict] = []
    ctx = await build_turn_context(
        pipeline=self,
        user_input=user_input,
        ...
        track_sse_callback=buffered_sse.append,
    )
    for evt in buffered_sse:
        yield _track_sse(evt)
    # ctx.messages, ctx.augmented_user, … are ready
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from haystack.dataclasses import ChatMessage

if TYPE_CHECKING:
    from src.agent_pipeline import AgentPipeline

logger = logging.getLogger("aion.turn_context")


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass
class TurnContext:
    """All context produced by the pre-flight build phase."""

    messages: List[ChatMessage]
    """STM window + user-turn message, after optional compression and budget truncation."""

    context_stats: Dict[str, Any]
    """Output of ``estimate_full_prompt_tokens`` plus ``message_count``."""

    augmented_user: str
    """Final user-input text after all injection layers have been prepended."""

    prompt_inject_layers: List[Dict[str, str]]
    """Ordered log of text injections prepended to ``augmented_user``."""

    qm_project: str
    """Resolved SQL-query-memory project slug."""

    qm_profile_slug: str
    """Profile slug used for QM gate checks."""

    effective_agent_mode: str
    """Resolved agent mode (e.g. ``'chat'``, ``'plan'``, ``'deep_research'``)."""


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


async def build_turn_context(
    pipeline: "AgentPipeline",
    *,
    user_input: str,
    attachments: Optional[List[Dict[str, Any]]],
    turn_attachments: Optional[List[Dict[str, Any]]],
    message_source: str,
    effective_agent_mode: str,
    sql_query_project: Optional[str],
    plan_execution_task_id: Optional[str],
    user_message_id: Optional[str],
    assistant_message_id: Optional[str],
    track_sse_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> TurnContext:
    """Build the full turn context, emitting any SSE side-effects via *track_sse_callback*.

    Parameters
    ----------
    pipeline:
        The ``AgentPipeline`` instance owning this turn.
    user_input:
        Raw user text for this turn.
    attachments:
        File/image attachments for the current turn (display blobs).
    turn_attachments:
        Turn-level attachment records (for DB persistence).
    message_source:
        One of ``'user_input'``, ``'internal_trigger'``, ``'scheduled_trigger'``.
    effective_agent_mode:
        Resolved agent mode string.
    sql_query_project:
        SQL query project override from the request.
    plan_execution_task_id:
        Explicit task ID when running a plan-execution turn.
    user_message_id:
        Pre-allocated user-message ID.
    assistant_message_id:
        Pre-allocated assistant-message ID.
    track_sse_callback:
        Callable invoked for each SSE dict this phase emits (e.g.
        ``context_compacting`` events).  The caller is responsible for
        yielding them to the client in the correct order.
    """
    from src.memory.ltm_orchestrator import ltm_orchestrator
    from src.memory.context_compressor import (
        estimate_agent_overhead_tokens,
        estimate_full_prompt_tokens,
        get_default_compressor,
        log_context_budget,
        truncate_messages_to_prompt_budget,
    )
    from src.api.history import history_manager
    from src.runtime.hooks import HookContext, hook_registry
    from src.runtime.prompt_snapshot import track_prepend_layer

    def _emit(evt: Dict[str, Any]) -> None:
        if track_sse_callback is not None:
            track_sse_callback(evt)

    _msg_src = (message_source or "user_input").strip()

    # ------------------------------------------------------------------
    # 1. Resolve SQL-query-memory project & profile slug
    # ------------------------------------------------------------------
    import os as _os_qm

    _qm_project = (
        sql_query_project or _os_qm.getenv("AION_SQL_QM_DEFAULT_PROJECT") or "default"
    ).strip()

    if not sql_query_project:
        try:
            from src.memory.sql_query_memory.conversation_project import (
                get_conversation_sql_project,
            )

            conv_proj = await get_conversation_sql_project(pipeline.session_id)
            if conv_proj:
                from src.runtime.sql_query_project_resolve import (
                    resolve_sql_query_project,
                )

                _qm_project = resolve_sql_query_project(
                    request_project=None,
                    conversation_project=conv_proj,
                )
        except Exception:
            pass

    from src.agent_profile import profile_manager as _pm_qm

    _prof_row = _pm_qm.get_profile(pipeline.profile_name)
    _qm_profile_slug = (
        _prof_row.slug if _prof_row else pipeline.profile_name.replace(" ", "_").lower()
    )

    # ------------------------------------------------------------------
    # 2. LTM wake-up
    # ------------------------------------------------------------------
    wake = await ltm_orchestrator.wake_up(pipeline.session_id)

    # ------------------------------------------------------------------
    # 3. STM window
    # ------------------------------------------------------------------
    from src.settings import get_settings as _get_settings

    _settings = _get_settings()
    max_turns = _settings.stm_max_turns
    tbudget = _settings.stm_token_budget
    stm_compressor = get_default_compressor()
    stm_overhead = estimate_agent_overhead_tokens(pipeline.agent)
    stm_msg_budget = stm_compressor.max_message_tokens(stm_overhead)
    if tbudget is not None:
        stm_msg_budget = min(stm_msg_budget, int(tbudget))
    stm_char_limit = min(60_000, max(12_000, stm_msg_budget * 4))

    stm_window = await history_manager.get_window(
        pipeline.session_id,
        pipeline.profile_name,
        max_turns=max_turns,
        token_budget=stm_msg_budget,
        char_limit=stm_char_limit,
        exclude_message_ids=[user_message_id] if user_message_id else None,
    )

    # ------------------------------------------------------------------
    # 4. Attachment block (for message assembly later)
    # ------------------------------------------------------------------
    attach_block = pipeline._format_attachments_block(attachments, turn_attachments)

    # ------------------------------------------------------------------
    # 5. Prompt-inject layers & user-input augmentation
    # ------------------------------------------------------------------
    _prompt_inject_layers: List[Dict[str, str]] = []
    _user_input_raw = user_input or ""

    # Skill-discovery nudge / plan-mode skill hint
    try:
        from src.agent_profile import profile_manager
        from src.runtime.skill_discovery_nudge import (
            build_plan_mode_skill_hint,
            build_skill_discovery_nudge,
            should_inject_skill_discovery_nudge,
        )

        prof = profile_manager.get_profile(pipeline.profile_name)
        has_hub = bool(prof and "skills_hub" in (prof.mcp_servers or []))
        mode = effective_agent_mode
        _pre_nudge = user_input
        if mode == "plan":
            plan_hint = build_plan_mode_skill_hint(user_input)
            if plan_hint:
                user_input = plan_hint + user_input
                track_prepend_layer(
                    _prompt_inject_layers,
                    "plan_mode_skill_hint",
                    _pre_nudge,
                    user_input,
                )
        elif should_inject_skill_discovery_nudge(
            user_input, profile_has_skills_hub=has_hub, agent_mode=mode
        ):
            user_input = build_skill_discovery_nudge(user_input) + user_input
            track_prepend_layer(
                _prompt_inject_layers,
                "skill_discovery_nudge",
                _pre_nudge,
                user_input,
            )
            logger.info(
                "skill_nudge_injected session=%s profile=%s",
                pipeline.session_id[:8],
                pipeline.profile_name,
            )
    except Exception as nudge_exc:
        logger.debug("skill nudge skipped: %s", nudge_exc)

    # Operational augmentation (tool summary + workspace manifest)
    _pre_augment = user_input
    augmented_user = await pipeline._augment_user_input(user_input)
    track_prepend_layer(
        _prompt_inject_layers,
        "operational_augment",
        _pre_augment,
        augmented_user,
    )

    # Pre-turn hooks (SQL QM, MemPalace nav, exploration tracker, datasource)
    from src.runtime.sql_query_memory_context import set_sql_qm_turn_context

    try:
        import src.runtime.query_memory_hooks  # noqa: F401 — register hooks
        import src.runtime.db_navigation_mempalace_hooks  # noqa: F401
        import src.runtime.exploration_tracker  # noqa: F401
        import src.runtime.datasource_memory_orchestrator  # noqa: F401

        _tenant_qm = (
            _os_qm.getenv("AION_DEFAULT_TENANT_ID") or "default"
        ).strip() or "default"
        _pre_hooks = augmented_user
        pre_turn_ctx = await hook_registry.dispatch(
            "pre_turn",
            HookContext(
                event="pre_turn",
                tenant_id=_tenant_qm,
                conversation_id=pipeline.session_id,
                user_id=pipeline.user_id,
                profile=pipeline.profile_name,
                payload={
                    "user_input": user_input,
                    "sql_query_project": _qm_project,
                },
            ),
        )
        mod = pre_turn_ctx.modified_payload or {}
        inject_sql = mod.get("sql_query_memory_inject")
        inject_nav = mod.get("mempalace_nav_inject")
        inject_explore = mod.get("exploration_reminder")
        inject_turn_reminder = mod.get("turn_state_reminder")
        inject_proj = mod.get("project_context_inject")
        inject_session = mod.get("session_entity_cache_inject")
        _sql_cache_hit = bool(mod.get("sql_query_memory_cache_hit"))
        _sql_cache_schemas = tuple(mod.get("sql_query_memory_cache_schemas") or ())
        _sql_cache_ids = tuple(mod.get("sql_query_memory_cache_hit_ids") or ())
        set_sql_qm_turn_context(
            user_id=pipeline.user_id,
            profile_slug=_qm_profile_slug,
            project_slug=_qm_project,
            session_id=pipeline.session_id,
            sql_cache_inject_active=_sql_cache_hit,
            sql_cache_schemas=_sql_cache_schemas,
            sql_cache_hit_ids=_sql_cache_ids,
        )
        _injections = [
            ("sql_query_memory", inject_sql),
            ("mempalace_nav", inject_nav),
            ("project_context", inject_proj),
            ("session_entity_cache", inject_session),
            ("exploration_reminder", inject_explore),
            ("turn_state_reminder", inject_turn_reminder),
        ]
        for _key, _text in _injections:
            if _text:
                _prompt_inject_layers.append({"key": _key, "text": str(_text)})
                augmented_user = str(_text) + "\n\n" + augmented_user

        if _msg_src == "internal_trigger":
            _artifact_exec_reminder = ""
            try:
                from src.runtime import orchestration_db as odb
                from src.runtime.orchestration_tools import resolve_active_plan_id
                from src.runtime.plan_engine import next_pending_task_id
                from src.runtime.plan_execution import build_plan_execution_reminder

                _active_pid = await resolve_active_plan_id(pipeline.session_id)
                if _active_pid:
                    _rec = await odb.fetch_plan_record(_active_pid)
                    _amd = (
                        (
                            _rec.get("approved_markdown")
                            or _rec.get("draft_markdown")
                            or ""
                        )
                        if _rec
                        else ""
                    ).strip()
                    _explicit_tid = (plan_execution_task_id or "").strip()
                    _ntid = _explicit_tid or (
                        next_pending_task_id(_amd) if _amd else None
                    )
                    _artifact_exec_reminder = build_plan_execution_reminder(
                        plan_id=_active_pid,
                        plan_markdown=_amd,
                        next_task_id=_ntid,
                        phase="start",
                    )
            except Exception:
                pass
            if not _artifact_exec_reminder:
                _artifact_exec_reminder = (
                    "<system-reminder>\n"
                    "Plan approved — execute ONE task, call mark_task_completed, then STOP.\n"
                    "</system-reminder>"
                )
            _prompt_inject_layers.append(
                {
                    "key": "plan_artifact_reminder",
                    "text": _artifact_exec_reminder + "\n\n",
                }
            )
            augmented_user = _artifact_exec_reminder + "\n\n" + augmented_user

        try:
            from src.runtime.datasource_memory_mode import (
                datasource_orchestrator_enabled,
            )

            if not datasource_orchestrator_enabled():
                from src.memory.project_memory_scope import (
                    project_context_block_async,
                    should_inject_project_context,
                )

                proj_ctx = await project_context_block_async(
                    _qm_project,
                    tenant_id=_tenant_qm,
                    profile_slug=_qm_profile_slug,
                )
                if proj_ctx and should_inject_project_context(
                    user_input, project_slug=_qm_project
                ):
                    _prompt_inject_layers.append(
                        {"key": "project_context", "text": str(proj_ctx)}
                    )
                    augmented_user = proj_ctx + "\n\n" + augmented_user
        except Exception as proj_ctx_exc:
            logger.debug("project context block skipped: %s", proj_ctx_exc)

    except Exception as qm_hook_exc:
        logger.debug("pre_turn memory hooks skipped: %s", qm_hook_exc)
        set_sql_qm_turn_context(
            user_id=pipeline.user_id,
            profile_slug=_qm_profile_slug,
            project_slug=_qm_project,
            session_id=pipeline.session_id,
        )
    else:
        try:
            from src.runtime.prompt_budget import apply_injection_budget

            _hook_keys = {
                "sql_query_memory",
                "mempalace_nav",
                "project_context",
                "session_entity_cache",
                "exploration_reminder",
                "turn_state_reminder",
                "plan_artifact_reminder",
            }
            _hook_layers = [
                e
                for e in _prompt_inject_layers
                if str(e.get("key") or "") in _hook_keys
            ]
            if _hook_layers and "_pre_hooks" in locals():
                augmented_user = apply_injection_budget(_pre_hooks, _hook_layers)
        except Exception as budget_exc:
            logger.debug("prompt budget skipped: %s", budget_exc)

    # LTM context retrieval
    _pre_ltm = augmented_user
    augmented_user = ltm_orchestrator.build_augmented_user_text(
        augmented_user, "", wake
    )
    track_prepend_layer(
        _prompt_inject_layers,
        "ltm_wake",
        _pre_ltm,
        augmented_user,
    )

    if attach_block.strip():
        _prompt_inject_layers.append({"key": "attachments_block", "text": attach_block})
    _prompt_inject_layers.append({"key": "user_input_raw", "text": _user_input_raw})
    if user_input != _user_input_raw:
        _prompt_inject_layers.append(
            {"key": "user_input_after_nudge", "text": user_input}
        )

    # ------------------------------------------------------------------
    # 6. Message list assembly
    # ------------------------------------------------------------------
    from src.agent_pipeline import _build_user_turn_chat_message

    messages: List[ChatMessage] = list(stm_window)
    messages.append(
        _build_user_turn_chat_message(
            pipeline.session_id,
            augmented_user,
            attachments,
            attach_block,
        )
    )

    # ------------------------------------------------------------------
    # 7. Context compression + token budget truncation
    # ------------------------------------------------------------------
    from src.runtime.redis_client import redis_consume_force_compact

    force_compact = await redis_consume_force_compact(pipeline.session_id)
    compressor_probe = get_default_compressor()
    overhead_probe = estimate_agent_overhead_tokens(pipeline.agent)
    compress_enabled = _settings.context_compress_enabled
    will_compact = force_compact or (
        compress_enabled
        and compressor_probe.should_compress(messages, fixed_overhead=overhead_probe)
    )
    if will_compact:
        _emit(
            {
                "type": "context_compacting",
                "active": True,
                "tokens": compressor_probe.total_with_overhead(
                    messages, overhead_probe
                ),
                "trigger": compressor_probe.compress_trigger_tokens(),
                "phase": "summarizing",
            }
        )


    logger.info(f"CONTEXT ENHANCEMENT DEBUG - force_compact: {force_compact}")
    

    messages, did_compact, reloaded_from_db = await pipeline._apply_context_compression(
        messages,
        force=force_compact,
        exclude_message_ids=[user_message_id] if user_message_id else None,
    )
    if reloaded_from_db:
        user_turn = _build_user_turn_chat_message(
            pipeline.session_id,
            augmented_user,
            attachments,
            attach_block,
        )
        from src.haystack_chat import chat_message_text

        if not messages or chat_message_text(messages[-1]) != chat_message_text(
            user_turn
        ):
            messages.append(user_turn)
    if did_compact:
        _emit(
            {
                "type": "context_compacting",
                "active": False,
                "tokens": compressor_probe.total_with_overhead(
                    messages, overhead_probe
                ),
                "phase": "done",
            }
        )

    post_stats = estimate_full_prompt_tokens(pipeline.agent, messages)
    context_stats = {
        **post_stats,
        "message_count": len(messages),
    }
    if post_stats["total"] >= post_stats["max_prompt"]:
        messages = truncate_messages_to_prompt_budget(
            messages,
            max_prompt_tokens=post_stats["max_prompt"],
            fixed_overhead=post_stats["overhead"],
            keep_last=max(1, compressor_probe.keep_last // 2),
        )
        log_context_budget(
            pipeline.session_id,
            estimate_full_prompt_tokens(pipeline.agent, messages),
            will_compact=False,
        )

    return TurnContext(
        messages=messages,
        context_stats=context_stats,
        augmented_user=augmented_user,
        prompt_inject_layers=_prompt_inject_layers,
        qm_project=_qm_project,
        qm_profile_slug=_qm_profile_slug,
        effective_agent_mode=effective_agent_mode,
    )
