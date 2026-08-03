"""Mnemos store + wake integration (SQLite)."""

from __future__ import annotations

import pytest

from src.data.engine import get_async_session_maker, init_engine
from src.data.models import Base
from src.memory.mnemos import store
from src.memory.mnemos.scope import user_scope
from src.memory.mnemos.wake import wake


@pytest.fixture()
def mnemos_db(monkeypatch, tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/mnemos.db"
    monkeypatch.setenv("AION_DB_URL", url)
    init_engine(url)
    import asyncio

    async def _create():
        async with get_async_session_maker()() as session:
            conn = await session.connection()
            await conn.run_sync(Base.metadata.create_all)

    asyncio.get_event_loop().run_until_complete(_create())
    return url


@pytest.mark.asyncio
async def test_insert_and_wake(mnemos_db):
    scope = user_scope("default", "tester")
    for i in range(5):
        await store.insert_note(scope, content=f"note number {i} about postgres", importance=3)
    rows = await wake(scope, k=10)
    assert len(rows) >= 1
    assert any("postgres" in (r.get("line") or "") for r in rows)


@pytest.mark.asyncio
async def test_supersede_chain(mnemos_db):
    scope = user_scope("default", "tester2")
    n1 = await store.insert_note(scope, content="works at company X", category="fact")
    n2 = await store.insert_note(scope, content="works at company Y", category="fact")
    await store.supersede_note(n1.id, n2)
    current = await store.follow_supersede_chain(n1)
    assert current.id == n2.id


@pytest.mark.asyncio
async def test_parallel_insert_unique_seq(mnemos_db):
    """Parallel memory_note calls must not collide on (scope, seq)."""
    import asyncio

    scope = user_scope("default", "parallel_tester")

    async def _add(i: int):
        return await store.insert_note(
            scope, content=f"parallel note {i} about systems", importance=3
        )

    notes = await asyncio.gather(*[_add(i) for i in range(8)])
    seqs = sorted(n.seq for n in notes)
    assert len(seqs) == len(set(seqs))
    assert seqs == list(range(8))
