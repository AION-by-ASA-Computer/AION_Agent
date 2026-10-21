"""API key personali: generazione, hash e validazione completa (unico punto di verità).

Formato ``aion_<prefix8>_<secret32>``. Nel DB si salva solo lo SHA-256 della
chiave completa: il segreto è casuale (~165 bit), quindi un hash lento come
bcrypt non aggiunge sicurezza e bloccherebbe l'event loop a ogni richiesta.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from src.security.api_key_parse import parse_api_key

from .scopes import ALLOWED_USER_SCOPES

logger = logging.getLogger("aion.auth.api_key")

__all__ = [
    "ApiKeyPrincipal",
    "authenticate_api_key",
    "generate_api_key",
    "hash_api_key",
    "parse_api_key",
    "scopes_from_json",
]

# ``last_used_at`` viene riscritto al massimo una volta per finestra.
_LAST_USED_RESOLUTION = timedelta(seconds=60)


@dataclass
class ApiKeyPrincipal:
    """Esito di una validazione riuscita: la chiave agisce come ``identifier``."""

    api_key_id: str
    user_row_id: str
    identifier: str
    tenant_id: str
    scopes: List[str] = field(default_factory=list)


def generate_api_key() -> tuple[str, str]:
    """Return ``(full_key, prefix8)``."""
    alphabet = string.ascii_lowercase + string.digits
    prefix = "".join(secrets.choice(alphabet) for _ in range(8))
    secret = "".join(secrets.choice(alphabet) for _ in range(32))
    return f"aion_{prefix}_{secret}", prefix


def hash_api_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def scopes_from_json(raw: str | None) -> List[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except Exception:
        return []
    return [str(s) for s in v] if isinstance(v, list) else []


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _reject(code: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail={"code": code, "message": message}
    )


async def authenticate_api_key(token: str) -> ApiKeyPrincipal:
    """Valida la chiave in sé (formato, esistenza, revoca, scadenza, proprietario).

    Gli scope restituiti sono già filtrati su ``ALLOWED_USER_SCOPES``; la verifica
    dello scope richiesto spetta alla dipendenza dell'endpoint.
    """
    prefix, secret = parse_api_key(token)
    if not prefix or not secret:
        raise _reject("api_key_invalid_format", "Invalid API key format")
    if os.getenv("AION_UNIFIED_DB", "1").lower() not in ("1", "true", "yes"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "API keys require the unified DB (AION_UNIFIED_DB=1)",
        )

    from sqlalchemy import select, update

    from src.data.engine import get_async_session_maker
    from src.data.models import ApiKey, User

    now = datetime.now(timezone.utc)
    async with get_async_session_maker()() as session:
        row = (
            await session.execute(select(ApiKey).where(ApiKey.hash == hash_api_key(token)))
        ).scalar_one_or_none()
        if row is None:
            raise _reject("api_key_invalid", "Invalid API key")
        if row.revoked_at is not None:
            raise _reject("api_key_revoked", "API key revoked")
        if row.expires_at is None or _as_utc(row.expires_at) <= now:
            raise _reject("api_key_expired", "API key expired")
        owner = await session.get(User, row.user_id) if row.user_id else None
        if owner is None or not owner.can_create_api_keys:
            raise _reject("api_key_owner_disabled", "API key owner is not enabled")

        principal = ApiKeyPrincipal(
            api_key_id=row.id,
            user_row_id=owner.id,
            identifier=owner.identifier,
            tenant_id=owner.tenant_id,
            scopes=[s for s in scopes_from_json(row.scopes_json) if s in ALLOWED_USER_SCOPES],
        )

        if row.last_used_at is None or now - _as_utc(row.last_used_at) >= _LAST_USED_RESOLUTION:
            try:
                await session.execute(
                    update(ApiKey).where(ApiKey.id == row.id).values(last_used_at=now)
                )
                await session.commit()
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("api key last_used_at update failed: %s", exc)
    return principal
