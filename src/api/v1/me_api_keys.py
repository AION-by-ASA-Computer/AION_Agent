"""API key personali dell'utente loggato (chat-ui → Impostazioni → API key).

Solo token chat: una API key non può creare né revocare chiavi. L'admin decide
per utente se la funzione è attiva, quante chiavi attive e la durata massima.
Views and policy checks are shared with the admin service-account endpoints
(``src/api/auth/api_key_view.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth.api_key_view import (
    check_new_key_allowed,
    key_policy,
    serialize_key,
    validated_scopes,
)
from src.api.auth.scopes import Scope
from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.data import api_keys as api_keys_db
from src.data.engine import get_async_session_maker
from src.data.models import User

router = APIRouter(prefix="/me/api-keys", tags=["v1-me-api-keys"])


class ApiKeyCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default_factory=lambda: [Scope.CHAT], min_length=1)
    expires_in_days: int = Field(..., ge=1)


def _me(auth: ChatAuthIdentity = Depends(require_chat_auth)) -> ChatAuthIdentity:
    if auth.via != "chat_token" or not auth.user_row_id:
        raise HTTPException(
            403,
            detail={
                "code": "user_token_required",
                "message": "User login token required",
            },
        )
    return auth


async def _load_user(session, user_row_id: str) -> User:
    user = await session.get(User, user_row_id)
    if user is None:
        raise HTTPException(401, detail="User not found")
    return user


@router.get("")
async def list_my_api_keys(auth: ChatAuthIdentity = Depends(_me)):
    now = datetime.now(timezone.utc)
    async with get_async_session_maker()() as session:
        user = await _load_user(session, auth.user_row_id)
        rows = await api_keys_db.list_user_keys(session, user.id)
        active = await api_keys_db.count_active(session, user.id)
    return {
        "policy": key_policy(user, active),
        "keys": [serialize_key(r, now) for r in rows],
    }


@router.post("", status_code=201)
async def create_my_api_key(
    body: ApiKeyCreateBody, auth: ChatAuthIdentity = Depends(_me)
):
    scopes = validated_scopes(body.scopes)
    async with get_async_session_maker()() as session:
        user = await _load_user(session, auth.user_row_id)
        active = await api_keys_db.count_active(session, user.id)
        check_new_key_allowed(user, expires_in_days=body.expires_in_days, active=active)
        row, full_key = await api_keys_db.create_user_key(
            session,
            user,
            name=body.name.strip(),
            scopes=scopes,
            ttl_days=body.expires_in_days,
        )
        await session.commit()
        out = serialize_key(row, datetime.now(timezone.utc))
    # Il segreto completo è restituito solo qui: nel DB resta solo lo SHA-256.
    return {**out, "key": full_key}


@router.delete("/{key_id}")
async def revoke_my_api_key(key_id: str, auth: ChatAuthIdentity = Depends(_me)):
    async with get_async_session_maker()() as session:
        row = await api_keys_db.revoke_key(session, auth.user_row_id, key_id)
        if row is None:
            raise HTTPException(404, detail="API key not found")
        await session.commit()
        out = serialize_key(row, datetime.now(timezone.utc))
    return out
