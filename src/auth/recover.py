"""CLI di emergenza: reimposta la password locale di un utente.

Dopo la migrazione a SSO gli utenti (admin compresi) non hanno piu' una
password locale. Se l'SSO smette di funzionare (secret scaduto, tenant IdP mal
configurato, ...) un admin rientra cosi'::

    # locale
    python -m src.auth.recover set-password admin
    # installazione Docker (install.sh), dalla directory di installazione
    docker compose -f docker-compose.ghcr.yml exec backend python -m src.auth.recover set-password admin

La pagina di login admin torna a mostrare il form password (un admin ne ha
una). La password stampata e' da cambiare al primo accesso; da li' l'admin puo'
riportare il login a "password" dalle impostazioni se l'SSO resta rotto.
"""

import argparse
import asyncio
import os
import secrets
import sys

from sqlalchemy import select


async def _set_password(identifier: str, password: str | None) -> int:
    import src.aion_env  # noqa: F401  (carica .env)
    from src.data.engine import get_async_session_maker
    from src.data.models import User
    from src.data.user_password import hash_password

    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()
    plain = password or secrets.token_urlsafe(12)
    async with get_async_session_maker()() as session:
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant, User.identifier == identifier)
            )
        ).scalars().first()
        if not user:
            print(f"User not found: {identifier}", file=sys.stderr)
            return 1
        user.password_hash = hash_password(plain)
        user.must_change_password = True
        user.temp_password_expires_at = None
        await session.commit()

    print(f"Password reset for {identifier}")
    if not password:
        print(f"Temporary password: {plain}")
    print("Change it at first login.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.auth.recover")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("set-password", help="reimposta la password locale di un utente")
    sp.add_argument("identifier")
    sp.add_argument("--password", help="password da impostare (default: generata)")
    args = ap.parse_args(argv[1:])
    return asyncio.run(_set_password(args.identifier, args.password))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
