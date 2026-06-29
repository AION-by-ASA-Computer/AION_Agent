from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.api.auth import AuthContext, Scope, require_scope
from src.api.v1.conversations import _require_unified
from src.data.engine import get_async_session_maker
from src.data.models import Conversation, Step
from src.data.ids import new_uuid7_str

router = APIRouter()


class StepCreate(BaseModel):
    name: str
    type: str
    input: Optional[str] = None
    output: Optional[str] = None
    parent_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/conversations/{conversation_id}/steps")
async def create_step(
    conversation_id: str,
    body: StepCreate,
    ctx: AuthContext = Depends(require_scope(Scope.CONVERSATIONS_WRITE)),
):
    _require_unified()
    sid = new_uuid7_str()
    async with get_async_session_maker()() as session:
        c = await session.get(Conversation, conversation_id)
        if not c or c.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "conversation not found")
        st = Step(
            id=sid,
            conversation_id=conversation_id,
            tenant_id=ctx.tenant_id,
            name=body.name,
            type=body.type,
            input=body.input,
            output=body.output,
            parent_id=body.parent_id,
            metadata_json=json.dumps(body.metadata or {}),
        )
        session.add(st)
        await session.commit()
    return {"id": sid}


@router.get("/conversations/{conversation_id}/steps")
async def list_steps(
    conversation_id: str,
    ctx: AuthContext = Depends(require_scope(Scope.CONVERSATIONS_READ)),
):
    _require_unified()
    async with get_async_session_maker()() as session:
        c = await session.get(Conversation, conversation_id)
        if not c or c.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "conversation not found")
        q = (
            select(Step)
            .where(Step.conversation_id == conversation_id)
            .order_by(Step.created_at)
        )
        rows = (await session.execute(q)).scalars().all()
    return {
        "data": [
            {
                "id": r.id,
                "name": r.name,
                "type": r.type,
                "input": r.input,
                "output": r.output,
                "parent_id": r.parent_id,
            }
            for r in rows
        ]
    }
