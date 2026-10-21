"""Operazioni DB sulle API key personali (endpoint utente ``/v1/me/api-keys`` e admin)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .ids import new_uuid7_str
from .models import ApiKey, User


def _active_clause(now: datetime):
    return (
        ApiKey.revoked_at.is_(None),
        or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
    )


async def list_user_keys(session: AsyncSession, user_id: str) -> List[ApiKey]:
    q = (
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


async def count_active(session: AsyncSession, user_id: str) -> int:
    now = datetime.now(timezone.utc)
    q = select(func.count(ApiKey.id)).where(ApiKey.user_id == user_id, *_active_clause(now))
    return int((await session.execute(q)).scalar() or 0)


async def count_active_by_user(session: AsyncSession) -> dict[str, int]:
    """``{user_id: chiavi attive}`` in un'unica query (lista utenti admin)."""
    now = datetime.now(timezone.utc)
    q = (
        select(ApiKey.user_id, func.count(ApiKey.id))
        .where(ApiKey.user_id.is_not(None), *_active_clause(now))
        .group_by(ApiKey.user_id)
    )
    return {uid: int(n) for uid, n in (await session.execute(q)).all()}


async def create_user_key(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    scopes: Iterable[str],
    ttl_days: int,
) -> tuple[ApiKey, str]:
    """Crea la chiave e restituisce ``(row, full_key)``; il chiamante fa commit."""
    from src.api.auth.api_key import generate_api_key, hash_api_key

    full_key, prefix = generate_api_key()
    row = ApiKey(
        id=new_uuid7_str(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=name,
        prefix=prefix,
        hash=hash_api_key(full_key),
        scopes_json=json.dumps(sorted(set(scopes))),
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days),
    )
    session.add(row)
    await session.flush()
    return row, full_key


async def revoke_key(session: AsyncSession, user_id: str, key_id: str) -> Optional[ApiKey]:
    """Revoca soft; ``None`` se la chiave non esiste o non è dell'utente."""
    row = await session.get(ApiKey, key_id)
    if row is None or row.user_id != user_id:
        return None
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
    return row


async def revoke_all_for_user(session: AsyncSession, user_id: str) -> int:
    res = await session.execute(
        update(ApiKey)
        .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    return int(res.rowcount or 0)


async def delete_all_for_user(session: AsyncSession, user_ids: Iterable[str]) -> int:
    ids = list(user_ids)
    if not ids:
        return 0
    res = await session.execute(delete(ApiKey).where(ApiKey.user_id.in_(ids)))
    return int(res.rowcount or 0)
