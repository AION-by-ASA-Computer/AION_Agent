"""Restrizione dei profili per utente (``user_profile_access``), valida per
chat token e API key (che agiscono come il proprietario)."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import HTTPException

logger = logging.getLogger("aion.api.profile_access")

# Profilo di default dei client: per un utente ristretto che non può usarlo si
# ripiega sul primo profilo consentito invece di rifiutare (come ``get_agent``).
_DEFAULT_PROFILE_SLUG = "aion_std"


async def allowed_profile_slugs(user_row_id: Optional[str]) -> List[str]:
    """Slug consentiti all'utente; lista vuota = nessuna restrizione."""
    if not user_row_id:
        return []
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import UserProfileAccess

    async with get_async_session_maker()() as session:
        rows = await session.execute(
            select(UserProfileAccess.profile_slug).where(
                UserProfileAccess.user_id == user_row_id
            )
        )
        return [r[0] for r in rows.all()]


async def enforce_profile_access(user_row_id: Optional[str], profile_name: str) -> str:
    """Profilo da usare per la richiesta; 403 ``profile_not_allowed`` se vietato."""
    allowed = await allowed_profile_slugs(user_row_id)
    if not allowed:
        return profile_name
    from src.agent_profile import ProfileNotFoundError, profile_manager

    try:
        slug = profile_manager.resolve_profile(profile_name).slug
    except ProfileNotFoundError:
        slug = profile_name
    if slug in allowed:
        return profile_name
    if slug == _DEFAULT_PROFILE_SLUG:
        return allowed[0]
    logger.warning("user %s denied access to profile %s", user_row_id, slug)
    raise HTTPException(
        403,
        detail={
            "code": "profile_not_allowed",
            "message": f"Profile '{profile_name}' is not allowed for this user",
        },
    )
