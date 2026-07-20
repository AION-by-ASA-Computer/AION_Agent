from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional, Set

MessageSource = Literal["user_input", "internal_trigger", "scheduled_trigger"]

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import AliasChoices, BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.agent_pipeline import AgentPipeline
from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.identity import sanitize_user_id
from src.main import get_agent, set_event_loop
from src.runtime.reasoning_effort import effective_reasoning_effort
from src.runtime.redis_client import redis_set_stream_cancel
from src.api.web_search_params import normalize_web_search_restrict_hosts

logger = logging.getLogger("aion.v1.chat")

router = APIRouter()

_prepare_tasks: Dict[str, asyncio.Task] = {}
_prepare_snapshots: Dict[str, Dict[str, Any]] = {}


class BackgroundChatRun:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.task: Optional[asyncio.Task] = None
        self.queues: Set[asyncio.Queue] = set()
        self.history: List[Dict[str, Any]] = []
        self.is_done = False
        self.error: Optional[str] = None


_background_runs: Dict[str, BackgroundChatRun] = {}


async def _run_pipeline_in_background(
    conversation_id: str,
    body: ChatStreamBody,
    uid: str,
    resolved_agent_mode: str,
    sql_project_resolved: Optional[str],
    att: Optional[list],
):
    run = _background_runs.get(conversation_id)
    if not run:
        return

    try:
        agent_instance, profile_name = await get_agent(
            body.profile,
            session_id=conversation_id,
            user_id=uid,
            agent_mode=resolved_agent_mode,
            message_source=body.message_source,
            llm_provider_name=body.llm_provider_name,
        )
        pipeline = AgentPipeline(
            agent=agent_instance,
            session_id=conversation_id,
            profile_name=profile_name,
            user_id=uid,
            agent_mode=resolved_agent_mode,
        )
        if body.thinking_enabled is False:
            resolved_effort = "min"
        else:
            resolved_effort = effective_reasoning_effort(body.reasoning_effort)

        async for chunk in pipeline.run_stream(
            body.message,
            attachments=att,
            reasoning_effort=resolved_effort,
            user_message_id=body.user_message_id,
            assistant_message_id=body.assistant_message_id,
            message_source=body.message_source,
            web_search_enabled=body.web_search_enabled,
            web_search_restrict_hosts=normalize_web_search_restrict_hosts(
                body.web_search_restrict_hosts
            ),
            sql_query_project=sql_project_resolved,
            metadata=body.metadata,
        ):
            event_data = {"event": "message", "data": json.dumps(chunk)}
            run.history.append(event_data)
            for q in list(run.queues):
                await q.put(event_data)

    except Exception as e:
        logger.error(
            "Error in background pipeline run for session %s: %s", conversation_id, e
        )
        from src.agent_profile import ProfileNotFoundError

        if isinstance(e, ProfileNotFoundError):
            payload = {
                "error": str(e),
                "code": "profile_not_found",
                "available_slugs": e.available_slugs,
            }
        else:
            payload = {"error": str(e)}
        error_event = {"event": "error", "data": json.dumps(payload)}
        run.error = str(e)
        run.history.append(error_event)
        for q in list(run.queues):
            await q.put(error_event)
    finally:
        run.is_done = True
        for q in list(run.queues):
            await q.put(None)
        _background_runs.pop(conversation_id, None)


def _prepare_dedupe_key(conversation_id: str, profile: str, user_id: str) -> str:
    return f"{conversation_id}\0{profile}\0{user_id}"


def _credential_user_id(auth: ChatAuthIdentity) -> str:
    if auth.user_row_id:
        return sanitize_user_id(auth.user_row_id)
    if auth.identifier:
        return sanitize_user_id(auth.identifier)
    return "default"


ReasoningEffort = Literal["min", "medium", "max"]


class AttachmentRef(BaseModel):
    relative_path: str
    original_name: Optional[str] = None
    mime: Optional[str] = None


class ChatStreamBody(BaseModel):
    conversation_id: str = Field(
        validation_alias=AliasChoices("conversation_id", "session_id"),
    )
    message: str
    attachments: Optional[List[AttachmentRef]] = None
    profile: str = Field(
        default="aion_std",
        validation_alias=AliasChoices("profile", "profile_slug", "profile_name"),
    )
    user_id: Optional[str] = None
    reasoning_effort: Optional[ReasoningEffort] = Field(
        default=None,
        description="Omit per default da env. min / medium / max (vedi agent-pipeline).",
    )
    thinking_enabled: Optional[bool] = None
    user_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    message_source: MessageSource = Field(
        default="user_input",
        description="Allineato a POST /chat legacy (trigger orchestrazione).",
    )
    web_search_enabled: Optional[bool] = None
    web_search_restrict_hosts: Optional[List[str]] = None
    agent_mode: Optional[str] = "normal"
    plan_mode: Optional[bool] = None
    deep_research_mode: Optional[bool] = None
    sql_query_project: Optional[str] = Field(
        default=None,
        description="Slug cassetto QueryMemory SQL (es. default, vendite, tecnico).",
    )
    llm_provider_name: Optional[str] = Field(
        default=None,
        description="Slug del provider LLM da usare per questa sessione (opzionale).",
    )
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True


class ChatPrepareBody(BaseModel):
    conversation_id: str
    profile: str = Field(
        default="aion_std",
        validation_alias=AliasChoices("profile", "profile_slug", "profile_name"),
    )
    user_id: Optional[str] = None
    agent_mode: Optional[str] = "normal"
    llm_provider_name: Optional[str] = Field(
        default=None,
        description="Slug del provider LLM da usare per questa sessione (opzionale).",
    )

    class Config:
        populate_by_name = True


@router.post("/chat/prepare")
async def chat_prepare(
    body: ChatPrepareBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    """
    Pre-avvia MCP stdio e popola la cache agente per una conversazione.
    Chiamare all'apertura della chat (prima del primo messaggio) per evitare cold-start.
    """
    uid = sanitize_user_id(body.user_id or x_aion_user_id or _credential_user_id(auth))
    dedupe_key = _prepare_dedupe_key(body.conversation_id, body.profile, uid)

    existing = _prepare_tasks.get(dedupe_key)
    if existing is not None and not existing.done():
        snap = _prepare_snapshots.get(dedupe_key) or {}
        return {
            "ok": True,
            "status": "warming",
            "conversation_id": body.conversation_id,
            "mcp_errors": snap.get("mcp_errors") or [],
            "has_errors": bool(snap.get("mcp_errors")),
        }

    from src.runtime.agent_mode_resolve import resolve_agent_mode

    resolved_agent_mode = resolve_agent_mode(
        body.agent_mode,
        None,
        message_source="internal_trigger",
    )

    _prepare_snapshots[dedupe_key] = {
        "status": "warming",
        "conversation_id": body.conversation_id,
        "profile": body.profile,
        "mcp_errors": [],
        "has_errors": False,
    }

    async def _run_prepare() -> None:
        status = "ready"
        try:
            await get_agent(
                body.profile,
                session_id=body.conversation_id,
                user_id=uid,
                agent_mode=resolved_agent_mode,
                message_source="internal_trigger",
                llm_provider_name=body.llm_provider_name,
            )
            logger.info(
                "chat prepare ready conv=%s profile=%s user=%s",
                body.conversation_id[:8] + "...",
                body.profile,
                uid,
            )
        except Exception as exc:
            status = "failed"
            logger.warning(
                "chat prepare failed conv=%s profile=%s: %s",
                body.conversation_id[:8] + "...",
                body.profile,
                exc,
            )
        finally:
            from src.runtime.mcp_health import format_session_mcp_errors

            mcp_errors = format_session_mcp_errors(body.conversation_id, body.profile)
            _prepare_snapshots[dedupe_key] = {
                "status": status,
                "conversation_id": body.conversation_id,
                "profile": body.profile,
                "mcp_errors": mcp_errors,
                "has_errors": bool(mcp_errors),
            }
            _prepare_tasks.pop(dedupe_key, None)

    _prepare_tasks[dedupe_key] = asyncio.create_task(
        _run_prepare(),
        name=f"chat-prepare-{body.conversation_id[:8]}",
    )
    return {
        "ok": True,
        "status": "warming",
        "conversation_id": body.conversation_id,
        "mcp_errors": [],
        "has_errors": False,
    }


@router.get("/chat/prepare/status")
async def chat_prepare_status(
    conversation_id: str = Query(...),
    profile: str = Query(...),
    user_id: Optional[str] = Query(None),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    """Stato warm MCP/agente per polling dalla chat-ui."""
    uid = sanitize_user_id(user_id or x_aion_user_id or _credential_user_id(auth))
    dedupe_key = _prepare_dedupe_key(conversation_id, profile, uid)
    task = _prepare_tasks.get(dedupe_key)
    if task is not None and not task.done():
        snap = _prepare_snapshots.get(dedupe_key) or {}
        return {
            "ok": True,
            "status": "warming",
            "conversation_id": conversation_id,
            "mcp_errors": snap.get("mcp_errors") or [],
            "has_errors": bool(snap.get("mcp_errors")),
        }
    snap = _prepare_snapshots.get(dedupe_key)
    if snap:
        return {"ok": True, **snap}
    from src.runtime.mcp_health import format_session_mcp_errors

    mcp_errors = format_session_mcp_errors(conversation_id, profile)
    return {
        "ok": True,
        "status": "idle",
        "conversation_id": conversation_id,
        "mcp_errors": mcp_errors,
        "has_errors": bool(mcp_errors),
    }


def _resolve_chat_user_id(
    auth: ChatAuthIdentity,
    *,
    body_user_id: Optional[str],
    x_aion_user_id: Optional[str],
) -> str:
    """Match legacy POST /chat: JWT identity wins over X-AION-User-Id."""
    if auth.via == "chat_token" and auth.identifier:
        return sanitize_user_id(auth.identifier)
    return sanitize_user_id(body_user_id or x_aion_user_id or _credential_user_id(auth))


@router.post("/chat/stop")
async def chat_stop(
    conversation_id: Optional[str] = Query(
        None, description="Conversation / session id"
    ),
    session_id: Optional[str] = Query(
        None, description="Legacy alias for conversation_id"
    ),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    cid = (conversation_id or session_id or "").strip()
    if not cid:
        raise HTTPException(400, detail="conversation_id or session_id required")
    await redis_set_stream_cancel(cid)
    return {"ok": True, "conversation_id": cid, "session_id": cid}


@router.post("/chat/stream")
async def chat_stream(
    body: ChatStreamBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    set_event_loop(asyncio.get_running_loop())
    uid = _resolve_chat_user_id(
        auth,
        body_user_id=body.user_id,
        x_aion_user_id=x_aion_user_id,
    )

    from src.runtime.agent_mode_resolve import resolve_agent_mode

    resolved_agent_mode = resolve_agent_mode(
        body.agent_mode,
        body.plan_mode,
        deep_research_mode=body.deep_research_mode,
        message_source=body.message_source,
    )

    sql_project_resolved = (body.sql_query_project or "").strip() or None
    conversation_project: str | None = None

    try:
        from opentelemetry import trace

        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.set_attribute("aion.session_id", body.conversation_id or "")
            current_span.set_attribute("aion.user_id", uid or "")
            current_span.set_attribute("aion.profile", body.profile or "")
            current_span.set_attribute("aion.tenant_id", "default")
            current_span.set_attribute("aion.user_question", body.message or "")
    except Exception as e:
        logger.warning("Failed to set trace attributes in chat_stream endpoint: %s", e)

    if os.getenv("AION_UNIFIED_DB", "1").lower() in ("1", "true", "yes"):
        try:
            from datetime import datetime, timezone
            from src.data.engine import get_async_session_maker
            from src.data.models import Conversation

            async with get_async_session_maker()() as session:
                r = await session.get(Conversation, body.conversation_id)
                if not r:
                    meta = {}
                    if body.thinking_enabled is not None:
                        meta["thinking_enabled"] = body.thinking_enabled
                    if body.reasoning_effort is not None:
                        meta["reasoning_effort"] = body.reasoning_effort
                    meta["agent_mode"] = resolved_agent_mode
                    if body.plan_mode is not None:
                        meta["plan_mode"] = body.plan_mode
                    if body.deep_research_mode is not None:
                        meta["deep_research_mode"] = body.deep_research_mode
                    if body.sql_query_project is not None:
                        meta["sql_query_project"] = body.sql_query_project
                    if body.llm_provider_name is not None:
                        meta["llm_provider_name"] = body.llm_provider_name

                    tenant = (
                        os.getenv("AION_DEFAULT_TENANT_ID") or "default"
                    ).strip() or "default"
                    r = Conversation(
                        id=body.conversation_id,
                        tenant_id=tenant,
                        user_id=uid,
                        profile_slug=body.profile,
                        title=None,
                        message_count=0,
                        metadata_json=json.dumps(meta),
                    )
                    session.add(r)
                    await session.commit()
                else:
                    meta = json.loads(r.metadata_json or "{}")
                    updated = False
                    if r.profile_slug != body.profile:
                        r.profile_slug = body.profile
                        updated = True
                    if (
                        body.thinking_enabled is not None
                        and meta.get("thinking_enabled") != body.thinking_enabled
                    ):
                        meta["thinking_enabled"] = body.thinking_enabled
                        updated = True
                    if (
                        body.reasoning_effort is not None
                        and meta.get("reasoning_effort") != body.reasoning_effort
                    ):
                        meta["reasoning_effort"] = body.reasoning_effort
                        updated = True
                    if meta.get("agent_mode") != resolved_agent_mode:
                        meta["agent_mode"] = resolved_agent_mode
                        updated = True
                    if (
                        body.plan_mode is not None
                        and meta.get("plan_mode") != body.plan_mode
                    ):
                        meta["plan_mode"] = body.plan_mode
                        updated = True
                    if (
                        body.sql_query_project is not None
                        and meta.get("sql_query_project") != body.sql_query_project
                    ):
                        meta["sql_query_project"] = body.sql_query_project
                        updated = True
                    if (
                        body.llm_provider_name is not None
                        and meta.get("llm_provider_name") != body.llm_provider_name
                    ):
                        meta["llm_provider_name"] = body.llm_provider_name
                        updated = True
                    if updated:
                        r.metadata_json = json.dumps(meta)
                        r.updated_at = datetime.now(timezone.utc)
                        session.add(r)
                        await session.commit()
                    conversation_project = (
                        meta.get("sql_query_project") or ""
                    ).strip() or None
        except Exception as e:
            logger.error(
                "Error ensuring/updating conversation metadata in v1 chat: %s", e
            )

    from src.runtime.sql_query_project_resolve import resolve_sql_query_project

    sql_project_resolved = resolve_sql_query_project(
        request_project=body.sql_query_project,
        conversation_project=conversation_project,
    )
    if sql_project_resolved:
        logger.info(
            "v1 chat sql_query_project resolved=%s request=%s conversation=%s conv=%s",
            sql_project_resolved,
            body.sql_query_project,
            conversation_project,
            body.conversation_id[:12],
        )

    _tenant_qm = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    _project_access_err: str | None = None
    try:
        from src.runtime.query_memory_hooks import profile_has_memory_capability_by_slug
        from src.runtime.sql_query_project_scope import verify_user_project_access

        if sql_project_resolved and profile_has_memory_capability_by_slug(body.profile):
            _project_access_err = await verify_user_project_access(
                project_slug=sql_project_resolved,
                tenant_id=_tenant_qm,
                user_id=uid,
                profile_slug=body.profile,
            )
    except Exception as access_exc:
        logger.warning("sql project access check skipped: %s", access_exc)

    att = None
    if body.attachments:
        att = [a.model_dump() for a in body.attachments]

    # Check if a background run is already active
    run = (
        _background_runs.get(body.conversation_id) if not _project_access_err else None
    )
    if not run and not _project_access_err:
        run = BackgroundChatRun(body.conversation_id)
        _background_runs[body.conversation_id] = run
        run.task = asyncio.create_task(
            _run_pipeline_in_background(
                conversation_id=body.conversation_id,
                body=body,
                uid=uid,
                resolved_agent_mode=resolved_agent_mode,
                sql_project_resolved=sql_project_resolved,
                att=att,
            ),
            name=f"chat-run-{body.conversation_id[:8]}",
        )

    q = asyncio.Queue()
    if run:
        for chunk in run.history:
            q.put_nowait(chunk)
        run.queues.add(q)

    async def gen():
        yield {"comment": "aion-open"}
        if _project_access_err:
            yield {"event": "error", "data": json.dumps({"error": _project_access_err})}
            return
        try:
            while True:
                chunk = await q.get()
                if chunk is None:
                    break
                yield chunk
        except asyncio.CancelledError:
            pass
        finally:
            if run and body.conversation_id in _background_runs:
                _background_runs[body.conversation_id].queues.discard(q)

    return EventSourceResponse(
        gen(),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/stream/reconnect/{conversation_id}")
async def chat_stream_reconnect(
    conversation_id: str,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    run = _background_runs.get(conversation_id)
    if not run:

        async def empty_gen():
            yield {"comment": "aion-not-active"}

        return EventSourceResponse(empty_gen())

    q = asyncio.Queue()
    for chunk in run.history:
        q.put_nowait(chunk)

    run.queues.add(q)

    async def gen():
        yield {"comment": "aion-open"}
        try:
            while True:
                chunk = await q.get()
                if chunk is None:
                    break
                yield chunk
        except asyncio.CancelledError:
            pass
        finally:
            if conversation_id in _background_runs:
                _background_runs[conversation_id].queues.discard(q)

    return EventSourceResponse(
        gen(),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
