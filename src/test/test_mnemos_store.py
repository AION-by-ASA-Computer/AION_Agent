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


@pytest.mark.anyio
async def test_insert_and_wake(mnemos_db):
    scope = user_scope("default", "tester")
    for i in range(5):
        await store.insert_note(
            scope, content=f"note number {i} about postgres", importance=3
        )
    rows = await wake(scope, k=10)
    assert len(rows) >= 1
    assert any("postgres" in (r.get("line") or "") for r in rows)


@pytest.mark.anyio
async def test_supersede_chain(mnemos_db):
    scope = user_scope("default", "tester2")
    n1 = await store.insert_note(scope, content="works at company X", category="fact")
    n2 = await store.insert_note(scope, content="works at company Y", category="fact")
    await store.supersede_note(n1.id, n2)
    n1 = await store.get_note(n1.id)
    assert n1 is not None
    current = await store.follow_supersede_chain(n1)
    assert current.id == n2.id


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_forgotten_note_not_in_current_fts_or_get(mnemos_db):
    """A soft-forgotten note (status=superseded, superseded_by=None) must NOT be returned in current mode."""
    scope = user_scope("default", "forgotten_tester")
    n = await store.insert_note(
        scope, content="secret api key alpha-bravo-123", importance=4
    )

    # Verify it is findable when active
    hits_active = await store.fts_search(scope, "alpha-bravo-123", mode="current")
    assert len(hits_active) == 1
    assert hits_active[0][0].id == n.id

    # Soft forget
    ok = await store.forget_note(n.id, hard=False)
    assert ok is True

    n_db = await store.get_note(n.id)
    assert n_db.status == "superseded"
    assert n_db.superseded_by is None

    # follow_supersede_chain must return None
    resolved = await store.follow_supersede_chain(n_db)
    assert resolved is None

    # fts_search in mode='current' must return nothing
    hits_current = await store.fts_search(scope, "alpha-bravo-123", mode="current")
    assert len(hits_current) == 0

    # fts_search in mode='historical' must return the superseded note
    hits_hist = await store.fts_search(scope, "alpha-bravo-123", mode="historical")
    assert len(hits_hist) == 1
    assert hits_hist[0][0].id == n.id
    assert hits_hist[0][0].status == "superseded"

    # get_notes_by_ids in mode='current' must return nothing
    by_ids_current = await store.get_notes_by_ids([n.id], mode="current")
    assert len(by_ids_current) == 0

    # get_notes_by_ids in mode='historical' must return it
    by_ids_hist = await store.get_notes_by_ids([n.id], mode="historical")
    assert len(by_ids_hist) == 1
    assert by_ids_hist[0].id == n.id


@pytest.mark.anyio
async def test_supersede_chain_resolution_and_invalidation(mnemos_db):
    """When A is superseded by B (active), search returns B. If B is also forgotten, search returns nothing."""
    scope = user_scope("default", "chain_tester")
    nA = await store.insert_note(
        scope, content="database server is MySQL 5.7", category="fact"
    )
    nB = await store.insert_note(
        scope, content="database server upgraded to PostgreSQL 16", category="fact"
    )
    await store.supersede_note(nA.id, nB)

    # Searching for MySQL should resolve to nB (PostgreSQL) in current mode
    hits = await store.fts_search(scope, "MySQL", mode="current")
    assert len(hits) == 1
    assert hits[0][0].id == nB.id
    assert hits[0][0].status == "active"

    # Now forget nB (the active replacement)
    await store.forget_note(nB.id, hard=False)
    nA_fresh = await store.get_note(nA.id)
    assert await store.follow_supersede_chain(nA_fresh) is None

    # Searching for MySQL in current mode should now return empty
    hits_after_forget = await store.fts_search(scope, "MySQL", mode="current")
    assert len(hits_after_forget) == 0


@pytest.mark.anyio
async def test_find_duplicate_note_exact_and_normalized(mnemos_db):
    """Normalized variations of the same text must be detected as duplicate."""
    scope = user_scope("default", "dedup_tester")
    n = await store.insert_note(
        scope, content="L'utente si chiama Alessio.", category="fact"
    )

    # Lowercase & without punctuation
    dup1 = await store.find_duplicate_note(scope, "l'utente si chiama alessio")
    assert dup1 is not None
    assert dup1.id == n.id

    # Extra spaces and exclamation mark
    dup2 = await store.find_duplicate_note(scope, "  L'utente  si  chiama  Alessio! ")
    assert dup2 is not None
    assert dup2.id == n.id

    # Different fact
    diff = await store.find_duplicate_note(scope, "L'utente lavora presso AION.")
    assert diff is None


@pytest.mark.anyio
async def test_orchestrator_add_note_dedup_does_not_create_new_row(mnemos_db):
    """Calling orchestrator.add_note with duplicate text must reinforce existing note and not create duplicate."""
    from src.memory.mnemos.orchestrator import mnemos_orchestrator

    res1 = await mnemos_orchestrator.add_note(
        tenant_id="default",
        user_id="alessio_dedup",
        text="L'utente lavora presso AION, azienda di intelligenza artificiale.",
        scope_name="user",
        category="fact",
        importance=4,
    )
    assert "id" in res1
    assert not res1.get("deduplicated")

    # Second call with identical/normalized text
    res2 = await mnemos_orchestrator.add_note(
        tenant_id="default",
        user_id="alessio_dedup",
        text="l'utente lavora presso aion, azienda di intelligenza artificiale!",
        scope_name="user",
        category="fact",
        importance=4,
    )
    assert res2.get("deduplicated") is True
    assert res2["id"] == res1["id"]
    assert res2["seq"] == res1["seq"]

    # Verify total notes in scope is exactly 1
    scope = user_scope("default", "alessio_dedup")
    notes = await store.list_notes(scope, limit=10)
    assert len(notes) == 1
    assert notes[0].id == res1["id"]
