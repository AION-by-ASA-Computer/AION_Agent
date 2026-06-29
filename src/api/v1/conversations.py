from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy import select, update

from src.api.auth import AuthContext, Scope, require_scope
from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.message_roles import (
    is_empty_technical_message,
    is_ui_visible_role,
    looks_like_internal_content,
    looks_like_raw_plan_content,
    normalize_message_role,
)
from src.data.models import Conversation

router = APIRouter()


class ConversationCreate(BaseModel):
    profile: str = Field(validation_alias=AliasChoices("profile", "profile_slug"))
    user_id: str
    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True


def _require_unified():
    if os.getenv("AION_UNIFIED_DB", "1").lower() not in ("1", "true", "yes"):
        raise HTTPException(
            503,
            "Unified DB disabled (set AION_UNIFIED_DB=0 to use legacy chat DB only)",
        )


@router.post("/conversations")
async def create_conversation(
    body: ConversationCreate,
    ctx: AuthContext = Depends(require_scope(Scope.CONVERSATIONS_WRITE)),
):
    _require_unified()
    cid = new_uuid7_str()
    async with get_async_session_maker()() as session:
        c = Conversation(
            id=cid,
            tenant_id=ctx.tenant_id,
            user_id=body.user_id,
            profile_slug=body.profile,
            title=body.title,
            metadata_json=json.dumps(body.metadata or {}),
            tags_json=json.dumps(body.tags or []),
        )
        session.add(c)
        await session.commit()
    return {
        "id": cid,
        "tenant_id": ctx.tenant_id,
        "user_id": body.user_id,
        "profile_slug": body.profile,
        "title": body.title,
        "message_count": 0,
        "metadata": body.metadata,
        "tags": body.tags,
    }


@router.get("/conversations")
async def list_conversations(
    user_id: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(require_scope(Scope.CONVERSATIONS_READ)),
):
    _require_unified()
    async with get_async_session_maker()() as session:
        q = select(Conversation).where(
            Conversation.tenant_id == ctx.tenant_id, Conversation.archived_at.is_(None)
        )
        if user_id:
            q = q.where(Conversation.user_id == user_id)
        q = q.order_by(Conversation.updated_at.desc()).limit(limit)
        rows = (await session.execute(q)).scalars().all()
    return {
        "data": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "profile_slug": r.profile_slug,
                "title": r.title,
                "message_count": r.message_count,
                "metadata": json.loads(r.metadata_json or "{}"),
                "tags": json.loads(r.tags_json or "[]"),
            }
            for r in rows
        ]
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    ctx: AuthContext = Depends(require_scope(Scope.CONVERSATIONS_READ)),
):
    _require_unified()
    async with get_async_session_maker()() as session:
        r = await session.get(Conversation, conversation_id)
    if not r or r.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Not found")
    return {
        "id": r.id,
        "user_id": r.user_id,
        "profile_slug": r.profile_slug,
        "title": r.title,
        "message_count": r.message_count,
        "metadata": json.loads(r.metadata_json or "{}"),
        "tags": json.loads(r.tags_json or "[]"),
    }


@router.patch("/conversations/{conversation_id}")
async def patch_conversation(
    conversation_id: str,
    body: Dict[str, Any],
    ctx: AuthContext = Depends(require_scope(Scope.CONVERSATIONS_WRITE)),
):
    _require_unified()
    async with get_async_session_maker()() as session:
        r = await session.get(Conversation, conversation_id)
        if not r or r.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "Not found")
        vals: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if "title" in body:
            vals["title"] = body["title"]
        if "tags" in body:
            vals["tags_json"] = json.dumps(body["tags"])
        if "metadata" in body:
            vals["metadata_json"] = json.dumps(body["metadata"])
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(**vals)
        )
        await session.commit()
    return await get_conversation(conversation_id, ctx)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    ctx: AuthContext = Depends(require_scope(Scope.CONVERSATIONS_WRITE)),
):
    _require_unified()
    async with get_async_session_maker()() as session:
        r = await session.get(Conversation, conversation_id)
        if not r or r.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "Not found")
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(archived_at=datetime.now(timezone.utc))
        )
        await session.commit()
    from src.mcp_manager import mcp_manager

    await mcp_manager.release_session(conversation_id)
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=1000),
    include_internal: bool = Query(False),
    ctx: AuthContext = Depends(require_scope(Scope.CONVERSATIONS_READ)),
):
    _require_unified()
    from src.data.models import Message

    async with get_async_session_maker()() as session:
        # Verify conversation belongs to tenant
        c = await session.get(Conversation, conversation_id)
        if not c or c.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "Conversation not found")

        q = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.seq.asc())
            .limit(limit)
        )
        rows = (await session.execute(q)).scalars().all()

    out = []
    for r in rows:
        nr = normalize_message_role(r.role)
        has_assistant_payload = nr == "assistant" and (
            bool((r.reasoning or "").strip())
            or bool((getattr(r, "timeline_json", None) or "").strip())
        )
        if not include_internal and (
            (not is_ui_visible_role(nr))
            or looks_like_internal_content(r.content)
            or looks_like_raw_plan_content(r.content)
            or (is_empty_technical_message(nr, r.content) and not has_assistant_payload)
        ):
            continue
        out.append(
            {
                "id": r.id,
                "role": nr,
                "content": r.content,
                "reasoning": r.reasoning,
                "tool_name": r.tool_name,
                "tool_call_id": r.tool_call_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return {"data": out}
