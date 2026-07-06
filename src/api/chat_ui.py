"""Endpoint compat per chat-ui: lista/crea conversazioni su schema unificato (senza API key v1)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import func, select
from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import AliasChoices, BaseModel, Field

from src.data.engine import get_async_session_maker
from src.data.history_bridge import (
    fetch_message_by_id,
    fetch_message_by_id_for_conversation,
)
from src.data.ids import new_uuid7_str
from src.data.models import Conversation, Message, Step, Attachment
from src.data.message_roles import (
    normalize_message_role,
    is_ui_visible_role,
    looks_like_internal_content,
    looks_like_raw_plan_content,
    is_empty_technical_message,
)
from src.khub_auth import khub_token_manager
from src.runtime.timeline_reconstruct import (
    parse_timeline_json,
    reconstruct_timeline_from_legacy,
)

logger = logging.getLogger("aion.api.chat_ui")


def _serialize_step_row(s: Step) -> Dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "type": s.type,
        "input": s.input,
        "output": s.output,
        "is_error": bool(s.is_error),
        "metadata_json": s.metadata_json,
        "created_at": s.created_at,
    }


def _serialize_attachment_row(a: Attachment) -> Dict[str, Any]:
    return {
        "id": a.id,
        "storage_key": a.storage_key,
        "original_name": a.original_name,
        "mime": a.mime,
        "size_bytes": a.size_bytes,
        "kind": a.kind,
        "created_at": a.created_at,
    }


def _resolve_message_timeline(
    msg_row: Message,
    steps: List[Dict[str, Any]],
    artifacts: List[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    parsed = parse_timeline_json(msg_row.timeline_json)
    if parsed is not None:
        return parsed
    return reconstruct_timeline_from_legacy(
        reasoning=msg_row.reasoning,
        content=msg_row.content,
        steps=steps,
        artifacts=artifacts,
    )


router = APIRouter(prefix="/chat-ui", tags=["chat-ui"])

_warned_no_secret = False


def _check_internal_secret(x_chat_ui_secret: Optional[str]) -> None:
    global _warned_no_secret
    expected = (os.getenv("AION_CHAT_UI_INTERNAL_SECRET") or "").strip()
    if not expected:
        if not _warned_no_secret:
            logger.warning(
                "AION_CHAT_UI_INTERNAL_SECRET unset: /chat-ui/* accepts any caller with X-AION-User-Id (dev only)."
            )
            _warned_no_secret = True
        return
    if (x_chat_ui_secret or "").strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid chat-ui secret")


def _require_unified():
    if os.getenv("AION_UNIFIED_DB", "1").lower() not in ("1", "true", "yes"):
        raise HTTPException(503, detail="Unified DB disabled")


class ConversationCreateBody(BaseModel):
    profile: str = Field(
        default="generic_assistant",
        validation_alias=AliasChoices("profile_name", "profile"),
    )
    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


@router.get("/conversations")
async def list_conversations_chat_ui(
    limit: int = Query(40, ge=1, le=200),
    exclude_scheduled: bool = Query(
        True, description="Hide cron/scheduled-job conversations from sidebar"
    ),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    async with get_async_session_maker()() as session:
        q = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant,
                Conversation.user_id == user_id,
                Conversation.archived_at.is_(None),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit * 4 if exclude_scheduled else limit)
        )
        rows = (await session.execute(q)).scalars().all()
    data = []
    for r in rows:
        meta = json.loads(r.metadata_json or "{}")
        if exclude_scheduled and meta.get("source") == "scheduled_job":
            continue
        data.append(
            {
                "id": r.id,
                "user_id": r.user_id,
                "profile_slug": r.profile_slug,
                "title": r.title,
                "message_count": r.message_count,
                "metadata": meta,
            }
        )
        if len(data) >= limit:
            break
    return {"data": data}


@router.post("/conversations")
async def create_conversation_chat_ui(
    body: ConversationCreateBody,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    cid = new_uuid7_str()
    async with get_async_session_maker()() as session:
        c = Conversation(
            id=cid,
            tenant_id=tenant,
            user_id=user_id,
            profile_slug=body.profile,
            title=body.title,
            metadata_json=json.dumps(body.metadata or {}),
            tags_json=json.dumps([]),
        )
        session.add(c)
        await session.commit()
    return {
        "id": cid,
        "user_id": user_id,
        "profile_slug": body.profile,
        "title": body.title,
        "message_count": 0,
        "metadata": body.metadata or {},
    }


@router.get("/conversations/{conv_id}/stream-status")
async def get_conversation_stream_status_chat_ui(
    conv_id: str,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    """Whether a /chat SSE turn is still running (client reconnect after navigation)."""
    _check_internal_secret(x_chat_ui_secret)
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"

    async with get_async_session_maker()() as session:
        conv = await session.get(Conversation, conv_id)
        if not conv or conv.tenant_id != tenant or conv.user_id != user_id:
            raise HTTPException(404, "Conversation not found")

    from src.runtime.redis_client import redis_get_stream_active

    meta = await redis_get_stream_active(conv_id)
    if not meta:
        return {"active": False}
    return {
        "active": True,
        "assistant_message_id": meta.get("assistant_message_id"),
        "user_message_id": meta.get("user_message_id"),
        "profile_name": meta.get("profile_name"),
        "started_at": meta.get("started_at"),
    }


def _message_metadata_dict(row: Message) -> Dict[str, Any]:
    raw_meta = getattr(row, "metadata_json", None)
    if not raw_meta:
        return {}
    try:
        parsed = json.loads(raw_meta)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _is_plan_tagged_internal(row: Message, nr: str, meta: Dict[str, Any]) -> bool:
    if nr != "internal":
        return False
    return bool((meta.get("plan_task_id") or "").strip())


@router.get("/conversations/{conv_id}/messages")
async def get_conversation_messages_chat_ui(
    conv_id: str,
    include_plan_internal: bool = False,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    """Retrieve full message history for a conversation including reasoning, tools and artifacts (chat-ui compat)."""
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"

    async with get_async_session_maker()() as session:
        conv = await session.get(Conversation, conv_id)
        if not conv:
            # Lazy chat route: /c/{uuid} exists before first POST /chat creates the row.
            return {"messages": []}
        if conv.tenant_id != tenant or conv.user_id != user_id:
            raise HTTPException(404, "Conversation not found")

        # Fetch Messages
        q_msg = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.seq.asc())
        )
        msgs = (await session.execute(q_msg)).scalars().all()
        last_msg_id = msgs[-1].id if msgs else None

        # Fetch Steps
        q_steps = (
            select(Step)
            .where(Step.conversation_id == conv_id)
            .order_by(Step.created_at.asc())
        )
        steps = (await session.execute(q_steps)).scalars().all()

        # Fetch Attachments
        q_att = (
            select(Attachment)
            .where(Attachment.conversation_id == conv_id)
            .order_by(Attachment.created_at.asc())
        )
        atts = (await session.execute(q_att)).scalars().all()

        # Group steps and attachments by message_id
        steps_by_msg = {}
        for s in steps:
            mid = s.message_id or "orphan"
            steps_by_msg.setdefault(mid, []).append(_serialize_step_row(s))

        atts_by_msg = {}
        for a in atts:
            mid = a.message_id or "orphan"
            atts_by_msg.setdefault(mid, []).append(_serialize_attachment_row(a))

        data = []

        for r in msgs:
            nr = normalize_message_role(r.role)
            meta = _message_metadata_dict(r)
            plan_internal = include_plan_internal and _is_plan_tagged_internal(
                r, nr, meta
            )

            current_steps = steps_by_msg.get(r.id, [])
            current_atts = atts_by_msg.get(r.id, [])

            has_assistant_payload = nr == "assistant" and (
                bool((r.reasoning or "").strip())
                or bool(current_steps)
                or bool(current_atts)
                or bool((r.timeline_json or "").strip())
            )
            is_terminal_assistant = nr == "assistant" and r.id == last_msg_id
            if (
                ((not is_ui_visible_role(nr)) and not plan_internal)
                or (looks_like_internal_content(r.content) and not plan_internal)
                or looks_like_raw_plan_content(r.content)
                or (
                    is_empty_technical_message(nr, r.content)
                    and not has_assistant_payload
                    and not is_terminal_assistant
                )
            ):
                continue

            timeline: Optional[List[Dict[str, Any]]] = None
            if nr == "assistant":
                timeline = _resolve_message_timeline(r, current_steps, current_atts)

            row: Dict[str, Any] = {
                "id": r.id,
                "role": nr,
                "content": r.content,
                "reasoning": r.reasoning,
                "tool_name": r.tool_name,
                "tool_call_id": r.tool_call_id,
                "created_at": r.created_at,
                "seq": r.seq,
                "steps": current_steps,
                "artifacts": current_atts,
            }
            if meta:
                row["metadata"] = meta
            if nr == "assistant":
                row["timeline"] = timeline
            data.append(row)

        return {"messages": data}


@router.get("/conversations/{conv_id}")
async def get_conversation_chat_ui(
    conv_id: str,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    async with get_async_session_maker()() as session:
        r = await session.get(Conversation, conv_id)
        if not r or r.tenant_id != tenant or r.user_id != user_id:
            raise HTTPException(404, "Not found")
        return {
            "id": r.id,
            "user_id": r.user_id,
            "profile_slug": r.profile_slug,
            "title": r.title,
            "message_count": r.message_count,
            "metadata": json.loads(r.metadata_json or "{}"),
        }


class ConversationUpdateMetadataBody(BaseModel):
    metadata: Optional[Dict[str, Any]] = None
    profile: Optional[str] = None
    profile_slug: Optional[str] = Field(default=None, alias="profile")
    title: Optional[str] = None

    class Config:
        populate_by_name = True


@router.patch("/conversations/{conv_id}/metadata")
async def update_conversation_metadata_chat_ui(
    conv_id: str,
    body: ConversationUpdateMetadataBody,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    async with get_async_session_maker()() as session:
        r = await session.get(Conversation, conv_id)
        if r:
            if r.tenant_id != tenant or r.user_id != user_id:
                raise HTTPException(404, "Not found")

            updated = False
            if body.metadata is not None:
                current_meta = json.loads(r.metadata_json or "{}")
                current_meta.update(body.metadata)
                r.metadata_json = json.dumps(current_meta)
                updated = True

            profile_to_set = body.profile or body.profile_slug
            if profile_to_set is not None:
                r.profile_slug = profile_to_set
                updated = True

            if body.title is not None:
                r.title = body.title
                updated = True

            if updated:
                r.updated_at = datetime.now(timezone.utc)
                session.add(r)
                await session.commit()
        else:
            # Creazione al volo se non esiste (upsert)
            r = Conversation(
                id=conv_id,
                tenant_id=tenant,
                user_id=user_id,
                profile_slug=body.profile or body.profile_slug or "generic_assistant",
                title=body.title,
                metadata_json=json.dumps(body.metadata or {}),
                tags_json=json.dumps([]),
            )
            session.add(r)
            await session.commit()
            r = await session.get(Conversation, conv_id)
            if not r:
                raise HTTPException(500, "Failed to create conversation")

        return {
            "id": r.id,
            "title": r.title,
            "metadata": json.loads(r.metadata_json or "{}"),
            "profile_slug": r.profile_slug,
        }


@router.delete("/conversations/{conv_id}/messages/{message_id}")
async def delete_turn_chat_ui(
    conv_id: str,
    message_id: str,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    """Prune conversation from the specified user message, deleting it and all subsequent turns, steps, and attachments."""
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"

    async with get_async_session_maker()() as session:
        # Verify the conversation exists and belongs to the user
        r = await session.get(Conversation, conv_id)
        if not r or r.tenant_id != tenant or r.user_id != user_id:
            raise HTTPException(404, "Conversation not found")

        # Verify the message exists and belongs to the conversation
        q_msg = select(Message).where(
            Message.id == message_id, Message.conversation_id == conv_id
        )
        msg_to_delete = (await session.execute(q_msg)).scalar_one_or_none()
        if not msg_to_delete:
            raise HTTPException(404, "Message not found")

        if msg_to_delete.role != "user":
            raise HTTPException(400, "Only user messages can trigger turn deletion")

        # Verify if this is the last user message in the conversation
        q_later_user = select(Message).where(
            Message.conversation_id == conv_id,
            Message.role == "user",
            Message.seq > msg_to_delete.seq,
        )
        later_user = (await session.execute(q_later_user)).scalars().first()
        if later_user:
            raise HTTPException(400, "Only the last user message turn can be deleted")

        # Get all message IDs that have seq >= msg_to_delete.seq
        q_subsequent = select(Message.id).where(
            Message.conversation_id == conv_id, Message.seq >= msg_to_delete.seq
        )
        subsequent_ids = (await session.execute(q_subsequent)).scalars().all()

        if subsequent_ids:
            from sqlalchemy import delete

            # Delete steps associated with these messages
            await session.execute(
                delete(Step).where(Step.message_id.in_(subsequent_ids))
            )
            # Delete attachments associated with these messages
            await session.execute(
                delete(Attachment).where(Attachment.message_id.in_(subsequent_ids))
            )
            # Delete the messages
            await session.execute(delete(Message).where(Message.id.in_(subsequent_ids)))

        # Recalculate message count of the conversation
        r.message_count = max(0, msg_to_delete.seq - 1)
        r.updated_at = datetime.now(timezone.utc)

        session.add(r)
        await session.commit()

        return {
            "success": True,
            "message_id": message_id,
            "message_count": r.message_count,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Salvataggio risposta parziale (Stop mid-stream)
# ──────────────────────────────────────────────────────────────────────────────


class MessageCreateBody(BaseModel):
    message_id: Optional[str] = None
    role: str = "assistant"
    content: str
    reasoning: Optional[str] = None
    timeline: Optional[List[Dict[str, Any]]] = None


class MessageTimelinePatchBody(BaseModel):
    timeline: List[Dict[str, Any]]


class StepItem(BaseModel):
    step_id: Optional[str] = None
    name: str
    type: str = "tool"
    input: Optional[str] = None
    output: Optional[str] = None
    is_error: bool = False
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class StepsBulkBody(BaseModel):
    steps: List[StepItem]


@router.post("/conversations/{conv_id}/messages")
async def save_partial_message_chat_ui(
    conv_id: str,
    body: MessageCreateBody,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    """Salva (o ignora se già presente) un messaggio assistente — usato per risposta parziale su Stop."""
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"

    async with get_async_session_maker()() as session:
        conv = await session.get(Conversation, conv_id)
        if not conv or conv.tenant_id != tenant or conv.user_id != user_id:
            raise HTTPException(404, "Conversation not found")

        mid = (body.message_id or "").strip() or new_uuid7_str()

        existing = await fetch_message_by_id_for_conversation(session, mid, conv_id)
        if not existing:
            cross = await fetch_message_by_id(session, mid)
            if cross and cross.conversation_id != conv_id:
                raise HTTPException(409, "Message id belongs to another conversation")

        role = normalize_message_role(body.role)
        timeline_json: Optional[str] = None
        if body.timeline:
            timeline_json = json.dumps(body.timeline, ensure_ascii=False)

        if existing:
            changed = False
            inc_content = (body.content or "").strip()
            if inc_content and existing.content != body.content:
                existing.content = body.content
                changed = True
            elif inc_content and not (existing.content or "").strip():
                existing.content = body.content
                changed = True
            if body.reasoning is not None and existing.reasoning != body.reasoning:
                existing.reasoning = body.reasoning
                changed = True
            if timeline_json and existing.timeline_json != timeline_json:
                existing.timeline_json = timeline_json
                changed = True
            if changed:
                conv.updated_at = datetime.now(timezone.utc)
                session.add(existing)
                session.add(conv)
                await session.commit()
                return {"saved": True, "message_id": mid, "reason": "updated"}
            return {"saved": False, "message_id": mid, "reason": "already_exists"}

        # Seq = max attuale + 1
        max_seq_result = await session.execute(
            select(func.max(Message.seq)).where(Message.conversation_id == conv_id)
        )
        max_seq = max_seq_result.scalar() or 0

        msg = Message(
            id=mid,
            conversation_id=conv_id,
            tenant_id=tenant,
            role=role,
            content=body.content,
            reasoning=body.reasoning,
            timeline_json=timeline_json,
            seq=max_seq + 1,
        )
        session.add(msg)

        conv.message_count = (conv.message_count or 0) + 1
        conv.updated_at = datetime.now(timezone.utc)
        session.add(conv)
        await session.commit()

    return {"saved": True, "message_id": mid}


@router.patch("/conversations/{conv_id}/messages/{message_id}/timeline")
async def patch_message_timeline_chat_ui(
    conv_id: str,
    message_id: str,
    body: MessageTimelinePatchBody,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    """Aggiorna solo timeline_json (es. backup client a fine stream)."""
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"

    async with get_async_session_maker()() as session:
        conv = await session.get(Conversation, conv_id)
        if not conv or conv.tenant_id != tenant or conv.user_id != user_id:
            raise HTTPException(404, "Conversation not found")
        msg = await fetch_message_by_id(session, message_id)
        if not msg or msg.conversation_id != conv_id:
            raise HTTPException(404, "Message not found")
        msg.timeline_json = json.dumps(body.timeline, ensure_ascii=False)
        await session.commit()
    return {"updated": True, "message_id": message_id}


@router.post("/conversations/{conv_id}/messages/{message_id}/steps")
async def save_partial_steps_chat_ui(
    conv_id: str,
    message_id: str,
    body: StepsBulkBody,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    """Salva in bulk step parziali (tool call) associati a un messaggio assistente."""
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"

    async with get_async_session_maker()() as session:
        conv = await session.get(Conversation, conv_id)
        if not conv or conv.tenant_id != tenant or conv.user_id != user_id:
            raise HTTPException(404, "Conversation not found")

        saved = 0
        for item in body.steps:
            meta = {}
            if item.tokens_in is not None:
                meta["tokens_in"] = item.tokens_in
            if item.tokens_out is not None:
                meta["tokens_out"] = item.tokens_out
            meta_str = json.dumps(meta) if meta else None

            sid = (item.step_id or "").strip() or new_uuid7_str()
            existing_step = await session.get(Step, sid)
            if existing_step:
                if existing_step.conversation_id != conv_id:
                    continue
                if item.output is not None:
                    existing_step.output = item.output
                if item.input is not None:
                    existing_step.input = item.input
                existing_step.is_error = 1 if item.is_error else 0
                if meta_str is not None:
                    existing_step.metadata_json = meta_str
                if not existing_step.message_id:
                    existing_step.message_id = message_id
                session.add(existing_step)
                saved += 1
                continue

            step = Step(
                id=sid,
                conversation_id=conv_id,
                tenant_id=tenant,
                message_id=message_id,
                name=item.name,
                type=item.type,
                input=item.input,
                output=item.output,
                is_error=1 if item.is_error else 0,
                metadata_json=meta_str,
            )
            session.add(step)
            saved += 1

        if saved:
            await session.commit()

    return {"saved": saved, "message_id": message_id}


@router.delete("/conversations/{conv_id}")
async def delete_conversation_chat_ui(
    conv_id: str,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    _check_internal_secret(x_chat_ui_secret)
    _require_unified()
    user_id = (x_aion_user_id or "").strip() or "default"
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"

    async with get_async_session_maker()() as session:
        r = await session.get(Conversation, conv_id)
        if not r or r.tenant_id != tenant or r.user_id != user_id:
            raise HTTPException(404, "Not found")

        r.archived_at = datetime.now(timezone.utc)
        session.add(r)
        await session.commit()

    try:
        from src.mcp_manager import mcp_manager

        await mcp_manager.release_session(conv_id)
    except Exception as e:
        logger.warning(
            "Failed to release MCP session for conversation %s: %s", conv_id, e
        )

    return {"success": True}


@router.get("/khub/file")
async def get_khub_file_endpoint(
    path: str = Query(..., description="The path to the file in KHUb"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
):
    """Retrieve file content from external Knowledge Hub (KHUb) service using OAuth2 client credentials.

    Authentication is delegated to the shared ``khub_token_manager`` singleton which
    caches and auto-renews the Keycloak token, avoiding a round-trip to Keycloak on
    every request.
    """
    _check_internal_secret(x_chat_ui_secret)

    api_endpoint = (os.getenv("KHUB_API_ENDPOINT") or "").strip()
    if not api_endpoint:
        logger.error("KHUb integration error: KHUB_API_ENDPOINT not configured.")
        raise HTTPException(
            status_code=500,
            detail="Knowledge Hub external API endpoint is not configured in backend environment.",
        )

    # 1. Obtain a valid Keycloak token via the shared manager (cached + auto-renewed).
    #    Returns None when KHUB_ISSUER / CLIENT_ID / CLIENT_SECRET are not set
    #    (dev-mode without Keycloak).
    access_token = await khub_token_manager.get_token()
    if access_token is None:
        logger.error(
            "KHUb authentication error: khub_token_manager returned None — "
            "check KHUB_ISSUER, KHUB_CLIENT_ID, KHUB_CLIENT_SECRET."
        )
        raise HTTPException(
            status_code=502,
            detail="Could not obtain a Keycloak access token for Knowledge Hub. "
            "Ensure KHUB_ISSUER, KHUB_CLIENT_ID and KHUB_CLIENT_SECRET are configured.",
        )

    # 2. Fetch file content from KHUB endpoint.
    clean_path = path.lstrip("/")
    khub_file_url = f"{api_endpoint.rstrip('/')}/files/{clean_path}/content/"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(
                khub_file_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            # If Keycloak rejected the token (e.g. it expired between cache-check and now),
            # invalidate the manager cache so the next caller gets a fresh token.
            if res.status_code == 401:
                khub_token_manager.invalidate()
                logger.warning(
                    "KHUb returned 401 for %s — token invalidated for next request.",
                    khub_file_url,
                )

            if res.status_code != 200:
                logger.error(
                    "KHUb API content retrieval error: %d - %s",
                    res.status_code,
                    res.text,
                )
                raise HTTPException(
                    status_code=res.status_code,
                    detail=f"Error from external Knowledge Hub: {res.text}",
                )

            content_type = res.headers.get("Content-Type", "")

            # Support both binary content and decoded JSON response format from KHUb.
            if "application/json" in content_type:
                try:
                    data = res.json()
                    file_content = data.get("content", "")
                    mime_type = data.get("mime_type", "application/pdf")
                    if isinstance(file_content, str):
                        file_bytes = file_content.encode("utf-8")
                    else:
                        file_bytes = bytes(file_content)
                except Exception as ex:
                    logger.error("Failed to parse JSON response from KHUb: %s", ex)
                    file_bytes = res.content
                    mime_type = "application/pdf"
            else:
                file_bytes = res.content
                mime_type = content_type or "application/pdf"

            return Response(content=file_bytes, media_type=mime_type)

    except httpx.HTTPError as e:
        logger.error("HTTP error connecting to KHUb at %s: %s", khub_file_url, e)
        raise HTTPException(
            status_code=502,
            detail=f"Network error connecting to Knowledge Hub: {str(e)}",
        )
