"""API key personali dell'utente loggato (chat-ui → Impostazioni → API key).

Solo token chat: una API key non può creare né revocare chiavi. L'admin decide
per utente se la funzione è attiva, quante chiavi attive e la durata massima.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth.api_key import scopes_from_json
from src.api.auth.scopes import ALLOWED_USER_SCOPES, Scope
from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.data import api_keys as api_keys_db
from src.data.engine import get_async_session_maker
from src.data.models import ApiKey, User

router = APIRouter(prefix="/me/api-keys", tags=["v1-me-api-keys"])


class ApiKeyCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default_factory=lambda: [Scope.CHAT], min_length=1)
    expires_in_days: int = Field(..., ge=1)


def _me(auth: ChatAuthIdentity = Depends(require_chat_auth)) -> ChatAuthIdentity:
    if auth.via != "chat_token" or not auth.user_row_id:
        raise HTTPException(
            403,
            detail={"code": "user_token_required", "message": "User login token required"},
        )
    return auth


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    v = _as_utc(dt)
    return v.isoformat() if v else None


def _serialize(row: ApiKey, now: datetime) -> dict:
    expires = _as_utc(row.expires_at)
    if row.revoked_at is not None:
        state = "revoked"
    elif expires is None or expires <= now:
        state = "expired"
    else:
        state = "active"
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "scopes": scopes_from_json(row.scopes_json),
        "created_at": _iso(row.created_at),
        "expires_at": _iso(row.expires_at),
        "last_used_at": _iso(row.last_used_at),
        "revoked_at": _iso(row.revoked_at),
        "status": state,
    }


def _policy(user: User, active: int) -> dict:
    return {
        "enabled": bool(user.can_create_api_keys),
        "max_keys": int(user.max_api_keys),
        "active_count": active,
        "max_ttl_days": int(user.api_key_max_ttl_days),
        "allowed_scopes": list(ALLOWED_USER_SCOPES),
    }


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
    return {"policy": _policy(user, active), "keys": [_serialize(r, now) for r in rows]}


@router.post("", status_code=201)
async def create_my_api_key(
    body: ApiKeyCreateBody, auth: ChatAuthIdentity = Depends(_me)
):
    scopes = sorted(set(body.scopes))
    invalid = [s for s in scopes if s not in ALLOWED_USER_SCOPES]
    if invalid:
        raise HTTPException(
            422,
            detail={"code": "invalid_scopes", "scopes": invalid, "message": "Invalid scopes"},
        )
    async with get_async_session_maker()() as session:
        user = await _load_user(session, auth.user_row_id)
        if not user.can_create_api_keys:
            raise HTTPException(
                403,
                detail={
                    "code": "api_keys_disabled",
                    "message": "API key creation is not enabled for this user",
                },
            )
        if body.expires_in_days > user.api_key_max_ttl_days:
            raise HTTPException(
                422,
                detail={
                    "code": "invalid_expiration",
                    "max_ttl_days": user.api_key_max_ttl_days,
                    "message": f"Expiration must be at most {user.api_key_max_ttl_days} days",
                },
            )
        active = await api_keys_db.count_active(session, user.id)
        if active >= user.max_api_keys:
            raise HTTPException(
                409,
                detail={
                    "code": "api_key_quota_exceeded",
                    "max_keys": user.max_api_keys,
                    "message": f"Active API key limit reached ({user.max_api_keys})",
                },
            )
        row, full_key = await api_keys_db.create_user_key(
            session,
            user,
            name=body.name.strip(),
            scopes=scopes,
            ttl_days=body.expires_in_days,
        )
        await session.commit()
        out = _serialize(row, datetime.now(timezone.utc))
    # Il segreto completo è restituito solo qui: nel DB resta solo lo SHA-256.
    return {**out, "key": full_key}


@router.delete("/{key_id}")
async def revoke_my_api_key(key_id: str, auth: ChatAuthIdentity = Depends(_me)):
    async with get_async_session_maker()() as session:
        row = await api_keys_db.revoke_key(session, auth.user_row_id, key_id)
        if row is None:
            raise HTTPException(404, detail="API key not found")
        await session.commit()
        out = _serialize(row, datetime.now(timezone.utc))
    return out
