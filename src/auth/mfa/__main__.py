"""CLI di emergenza: ``python -m src.auth.mfa reset <identifier>``."""

import asyncio
import os
import sys

from sqlalchemy import select


async def _reset(identifier: str) -> int:
    import src.aion_env  # noqa: F401  (carica .env)
    from src.auth.mfa.totp import reset_user_totp
    from src.data.engine import get_async_session_maker
    from src.data.models import User

    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()
    async with get_async_session_maker()() as session:
        res = await session.execute(
            select(User).where(User.tenant_id == tenant, User.identifier == identifier)
        )
        user = res.scalars().first()
    if not user:
        print(f"User not found: {identifier}", file=sys.stderr)
        return 1
    await reset_user_totp(user.id)
    print(f"2FA reset for {identifier}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "reset":
        print("usage: python -m src.auth.mfa reset <identifier>", file=sys.stderr)
        return 2
    return asyncio.run(_reset(argv[2]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
