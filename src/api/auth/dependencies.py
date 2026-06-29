from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

from fastapi import Depends, Header, HTTPException, status

from .api_key import parse_api_key, verify_api_key
from .scopes import Scope

logger = logging.getLogger("aion.auth")


@dataclass
class AuthContext:
    tenant_id: str = "default"
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    scopes: List[str] = field(default_factory=list)


def _scopes_from_json(raw: str | None) -> List[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return list(v) if isinstance(v, list) else []
    except Exception:
        return []


async def require_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
) -> AuthContext:
    token = (x_api_key or "").strip()
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
    prefix, secret = parse_api_key(token)
    if not prefix or not secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key format")
    boot = (os.getenv("AION_API_KEY_BOOTSTRAP") or "").strip()
    if boot and token == boot:
        return AuthContext(
            tenant_id="default",
            user_id=None,
            api_key_id="bootstrap",
            scopes=[
                Scope.ADMIN,
                Scope.CHAT,
                Scope.CONVERSATIONS_READ,
                Scope.CONVERSATIONS_WRITE,
                Scope.FILES_READ,
                Scope.FILES_WRITE,
            ],
        )
    if os.getenv("AION_UNIFIED_DB", "1").lower() not in ("1", "true", "yes"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Persisted API keys require the unified DB (clear AION_UNIFIED_DB=0) or use AION_API_KEY_BOOTSTRAP",
        )
    from sqlalchemy import select
    from src.data.engine import get_async_session_maker
    from src.data.models import ApiKey

    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(ApiKey).where(
                        ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .first()
        )
    if not row or not verify_api_key(token, row.hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return AuthContext(
        tenant_id=row.tenant_id,
        api_key_id=row.id,
        scopes=_scopes_from_json(row.scopes_json),
    )


async def optional_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
) -> Optional[AuthContext]:
    if not (x_api_key or authorization):
        return None
    return await require_auth(authorization=authorization, x_api_key=x_api_key)


def require_scope(scope: str):
    async def _dep(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
        if Scope.ADMIN in ctx.scopes or scope in ctx.scopes:
            return ctx
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing scope {scope}")

    return _dep
