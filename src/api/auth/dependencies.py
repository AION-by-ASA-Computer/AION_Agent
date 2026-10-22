from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from fastapi import Depends, Header, HTTPException, status

from .api_key import authenticate_api_key

logger = logging.getLogger("aion.auth")


@dataclass
class AuthContext:
    tenant_id: str = "default"
    # Identifier del proprietario della chiave (stesso principal del chat token).
    user_id: Optional[str] = None
    user_row_id: Optional[str] = None
    api_key_id: Optional[str] = None
    scopes: List[str] = field(default_factory=list)


async def require_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
) -> AuthContext:
    token = (x_api_key or "").strip()
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
    p = await authenticate_api_key(token)
    return AuthContext(
        tenant_id=p.tenant_id,
        user_id=p.identifier,
        user_row_id=p.user_row_id,
        api_key_id=p.api_key_id,
        scopes=list(p.scopes),
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
        if scope in ctx.scopes:
            return ctx
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "missing_scope",
                "scope": scope,
                "message": f"Missing scope {scope}",
            },
        )

    return _dep
