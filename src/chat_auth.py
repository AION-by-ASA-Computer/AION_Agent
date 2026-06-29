"""Password authentication for chat-ui (users table in ``AION_DB_URL``).

Legacy env aliases ``AION_CHAINLIT_PASSWORD_AUTH`` / ``CHAINLIT_AUTH_SECRET`` are
still read as fallback; ``scripts/upgrade_core.py`` migrates them to ``AION_CHAT_*``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, Optional

import bcrypt
from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.models import User

logger = logging.getLogger("aion.chat_auth")


def password_auth_enabled() -> bool:
    raw = (
        os.getenv("AION_CHAT_PASSWORD_AUTH")
        or os.getenv("AION_CHAINLIT_PASSWORD_AUTH")
        or "0"
    )
    return raw.lower() in ("1", "true", "yes")


def chat_auth_secret() -> str:
    return (
        os.getenv("AION_CHAT_AUTH_SECRET") or os.getenv("CHAINLIT_AUTH_SECRET") or ""
    ).strip()


async def authenticate_user_password(
    username: str, password: str
) -> Optional[Dict[str, Any]]:
    """Verify credentials on ``users``; return a serializable dict or None."""
    if not username or not password:
        return None
    key = username.strip()
    tenant_id = os.getenv("AION_DEFAULT_TENANT_ID", "default")

    async with get_async_session_maker()() as session:
        u_res = (
            (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant_id, User.identifier == key
                    )
                )
            )
            .scalars()
            .all()
        )
        u = u_res[0] if u_res else None

        if not u:
            u_res = (
                (
                    await session.execute(
                        select(User).where(
                            User.tenant_id == tenant_id, User.identifier.ilike(key)
                        )
                    )
                )
                .scalars()
                .all()
            )
            u = u_res[0] if u_res else None

        if not u:
            return None

        ph = u.password_hash
        if not ph:
            logger.warning("User %s has no password_hash in DB", key)
            return None

        try:
            ok = bcrypt.checkpw(password.encode("utf-8"), ph.encode("utf-8"))
        except ValueError:
            return None

        if not ok:
            return None

        meta_out: Dict[str, Any] = {}
        if u.metadata_json:
            try:
                meta_out = json.loads(u.metadata_json)
            except json.JSONDecodeError:
                pass
        meta_out["username"] = u.identifier
        if u.email:
            meta_out["email"] = u.email

        from src.data.user_password import get_roles

        return {
            "id": u.id,
            "identifier": u.identifier,
            "display_name": u.display_name or u.identifier,
            "metadata": meta_out,
            "roles": get_roles(u),
            "must_change_password": bool(getattr(u, "must_change_password", False)),
        }


def warn_if_auth_misconfigured() -> None:
    if not password_auth_enabled():
        return
    if not chat_auth_secret():
        logger.warning(
            "AION_CHAT_PASSWORD_AUTH is enabled but AION_CHAT_AUTH_SECRET is unset "
            "(legacy alias: CHAINLIT_AUTH_SECRET). "
            "Generate with: openssl rand -hex 32"
        )


if __name__ == "__main__":
    # Usage: python -m src.chat_auth hash [password]
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) >= 2 and sys.argv[1] == "hash":
        pw = sys.argv[2] if len(sys.argv) > 2 else input("Password: ")
        h = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")
        print(h)
    else:
        print("Usage: python -m src.chat_auth hash [password]")
        sys.exit(1)
