#!/usr/bin/env python3
"""Migra chiavi credenziali email: IMAP_USER -> EMAIL_USER, IMAP_PASSWORD -> EMAIL_PASSWORD."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_KEY_MAP = {
    "IMAP_USER": "EMAIL_USER",
    "IMAP_PASSWORD": "EMAIL_PASSWORD",
}


async def migrate(server_slug: str, *, dry_run: bool) -> int:
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import UserMcpCredential
    from src.runtime.credential_store import decrypt_value, encrypt_value

    moved = 0
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(UserMcpCredential).where(
                        UserMcpCredential.server_slug == server_slug
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            new_key = _KEY_MAP.get(row.credential_key)
            if not new_key:
                continue
            exists = (
                (
                    await session.execute(
                        select(UserMcpCredential.id).where(
                            UserMcpCredential.user_id == row.user_id,
                            UserMcpCredential.tenant_id == row.tenant_id,
                            UserMcpCredential.server_slug == row.server_slug,
                            UserMcpCredential.credential_key == new_key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if exists:
                print(f"skip {row.user_id}: {new_key} already set")
                continue
            plain = decrypt_value(row.value_encrypted)
            print(
                f"{'would move' if dry_run else 'move'} {row.user_id}: {row.credential_key} -> {new_key}"
            )
            if not dry_run:
                row.credential_key = new_key
                row.value_encrypted = encrypt_value(plain)
            moved += 1
        if not dry_run:
            await session.commit()
    return moved


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", default="email-mcp-server")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    n = asyncio.run(migrate(args.slug, dry_run=args.dry_run))
    print(f"Done. Keys migrated: {n}")


if __name__ == "__main__":
    main()
