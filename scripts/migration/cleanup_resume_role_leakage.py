#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from typing import Iterable

from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.message_roles import looks_like_internal_content
from src.data.models import Message


def _snippet(text: str, n: int = 120) -> str:
    t = " ".join((text or "").split())
    return t[:n] + ("..." if len(t) > n else "")


async def _load_candidates(conversation_id: str | None) -> Iterable[Message]:
    maker = get_async_session_maker()
    async with maker() as session:
        q = select(Message).where(Message.role == "user")
        if conversation_id:
            q = q.where(Message.conversation_id == conversation_id)
        q = q.order_by(Message.created_at.asc())
        rows = (await session.execute(q)).scalars().all()
        return [m for m in rows if looks_like_internal_content(m.content)]


async def _apply(messages: Iterable[Message]) -> int:
    maker = get_async_session_maker()
    ids = [m.id for m in messages]
    if not ids:
        return 0
    async with maker() as session:
        q = select(Message).where(Message.id.in_(ids))
        rows = (await session.execute(q)).scalars().all()
        for m in rows:
            m.role = "internal"
        await session.commit()
        return len(rows)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cleanup legacy role leakage: retag suspicious user messages as internal."
    )
    parser.add_argument(
        "--conversation-id",
        default=None,
        help="Restrict cleanup to one conversation id.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag the script runs in dry-run mode.",
    )
    args = parser.parse_args()

    candidates = list(await _load_candidates(args.conversation_id))
    print(
        f"[cleanup] candidates={len(candidates)} conversation={args.conversation_id or 'ALL'}"
    )
    for m in candidates[:40]:
        print(f"- {m.conversation_id} | {m.id} | role={m.role} | {_snippet(m.content)}")
    if len(candidates) > 40:
        print(f"... and {len(candidates) - 40} more")

    if not args.apply:
        print("[cleanup] dry-run only. Use --apply to persist changes.")
        return

    updated = await _apply(candidates)
    print(f"[cleanup] updated={updated} rows set to role='internal'")


if __name__ == "__main__":
    asyncio.run(main())
