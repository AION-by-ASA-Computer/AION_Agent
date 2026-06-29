"""Creazione utenti con password (bcrypt) nel DB unificato — condiviso da Admin API, setup e CLI."""

from __future__ import annotations

import json
import logging
from typing import Iterable, List, Optional

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .engine import get_async_session_maker
from .ids import new_uuid7_str
from .models import User

logger = logging.getLogger("aion.data.user_password")


class UserAlreadyExistsError(Exception):
    """Esiste già un utente con lo stesso (tenant_id, identifier)."""

    def __init__(self, tenant_id: str, identifier: str) -> None:
        self.tenant_id = tenant_id
        self.identifier = identifier
        super().__init__(
            f"User already exists: tenant={tenant_id!r} identifier={identifier!r}"
        )


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "ascii"
    )


def verify_password(plain: str, hashed: Optional[str]) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --- Roles -----------------------------------------------------------------


def get_roles(u: User) -> List[str]:
    """Decodifica ``users.roles`` (JSON list). Robusto a valori legacy."""
    raw = getattr(u, "roles_json", None) or "[]"
    try:
        v = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if isinstance(x, (str, int))]


def has_role(u: User, role: str) -> bool:
    return role in get_roles(u)


def set_roles(u: User, roles: Iterable[str]) -> None:
    seen: set[str] = set()
    out: List[str] = []
    for r in roles:
        if not r:
            continue
        s = str(r).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    u.roles_json = json.dumps(out)


# --- Creazione utente ------------------------------------------------------


async def create_password_user(
    *,
    tenant_id: str,
    identifier: str,
    password: str,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    roles: Optional[Iterable[str]] = None,
    must_change_password: bool = False,
    session_maker: Optional[async_sessionmaker[AsyncSession]] = None,
) -> str:
    """Inserisce una riga ``users`` con ``password_hash`` bcrypt. Ritorna l'id utente.

    ``roles``: lista di ruoli (es. ``["admin"]``). Default lista vuota.
    ``must_change_password``: True per forzare il banner "cambia password" lato
    client al primo login (stile Grafana). Non blocca l'accesso.
    """
    key = identifier.strip()
    if not key or not password:
        raise ValueError("identifier e password sono obbligatori")

    sm = session_maker or get_async_session_maker()
    hashed = hash_password(password)
    roles_list = list(roles or [])

    async with sm() as session:
        existing = (
            (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant_id, User.identifier == key
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing:
            raise UserAlreadyExistsError(tenant_id, key)

        new_user = User(
            id=new_uuid7_str(),
            tenant_id=tenant_id,
            identifier=key,
            display_name=display_name,
            email=email,
            password_hash=hashed,
            must_change_password=bool(must_change_password),
        )
        set_roles(new_user, roles_list)
        session.add(new_user)
        await session.commit()
        return new_user.id


async def admin_exists(
    *,
    tenant_id: str,
    session_maker: Optional[async_sessionmaker[AsyncSession]] = None,
) -> bool:
    """True se esiste almeno un utente con ruolo ``admin`` nel tenant.

    NB: implementazione semplice via scan + parse, non query-based (LIKE su
    JSON e' fragile). Per cataloghi grandi normalizzare a tabella user_roles.
    """
    sm = session_maker or get_async_session_maker()
    async with sm() as session:
        rows = (
            (await session.execute(select(User).where(User.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        for u in rows:
            if has_role(u, "admin"):
                return True
        return False
