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
    import src.data.engine as engine

    if engine._engine is not None:
        import asyncio

        asyncio.run(engine._engine.dispose())
    engine._engine = None
    engine._session_factory = None
    url = f"sqlite+aiosqlite:///{tmp_path}/mnemos.db"
    monkeypatch.setenv("AION_DB_URL", url)
    init_engine(url)
    import asyncio

    async def _create():
        async with get_async_session_maker()() as session:
            conn = await session.connection()
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    return url


@pytest.mark.asyncio
async def test_insert_and_wake(mnemos_db):
    scope = user_scope("default", "tester")
    for i in range(5):
        await store.insert_note(
            scope, content=f"note number {i} about postgres", importance=3
        )
    rows = await wake(scope, k=10)
    assert len(rows) >= 1
    assert any("postgres" in (r.get("line") or "") for r in rows)


@pytest.mark.asyncio
async def test_supersede_chain(mnemos_db):
    scope = user_scope("default", "tester2")
    n1 = await store.insert_note(scope, content="works at company X", category="fact")
    n2 = await store.insert_note(scope, content="works at company Y", category="fact")
    await store.supersede_note(n1.id, n2)
    n1 = await store.get_note(n1.id)
    assert n1 is not None
    current = await store.follow_supersede_chain(n1)
    assert current.id == n2.id


@pytest.mark.asyncio
async def test_insert_notes_bulk_matches_loop(mnemos_db):
    """Bulk insert should produce same row count, seq range, and FTS hits as a loop."""
    from src.memory.mnemos.scope import project_scope

    contents = [
        "bulk alpha note about laptops",
        "bulk beta note about servicenow",
        "bulk gamma note about incident mobile",
    ]
    scope_loop = project_scope("default", "bulk_loop")
    scope_bulk = project_scope("default", "bulk_bulk")

    for text in contents:
        await store.insert_note(scope_loop, content=text, importance=3)
    bulk_count = await store.insert_notes_bulk(
        scope_bulk, contents, importance=3, source_session_id="bulk_test"
    )

    assert bulk_count == len(contents)
    loop_notes = await store.list_notes(scope_loop, limit=100)
    bulk_notes = await store.list_notes(scope_bulk, limit=100)
    assert len(loop_notes) == len(bulk_notes) == len(contents)
    assert (
        sorted(n.seq for n in loop_notes)
        == sorted(n.seq for n in bulk_notes)
        == list(range(len(contents)))
    )

    loop_hits = await store.fts_search(scope_loop, "laptops servicenow", limit=10)
    bulk_hits = await store.fts_search(scope_bulk, "laptops servicenow", limit=10)
    assert {n.content for n, _ in loop_hits} == {n.content for n, _ in bulk_hits}


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
