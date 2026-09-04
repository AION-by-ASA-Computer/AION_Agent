"""Tripwires for Mnemos defects found by the adversarial benchmark.

When a fix lands the corresponding test must pass without xfail markers.
See docs/benchmarks/mnemos-bench.md#adversarial-suite for the analysis.
"""

from __future__ import annotations

import pytest

from src.data.engine import get_async_session_maker, init_engine
from src.data.models import Base
from src.memory.mnemos import store
from src.memory.mnemos.fts import build_fts_queries
from src.memory.mnemos.recall import recall_across_scopes
from src.memory.mnemos.scope import project_scope, user_scope


@pytest.fixture()
def mnemos_db(monkeypatch, tmp_path):
    import src.data.engine as engine

    if engine._engine is not None:
        import asyncio

        asyncio.run(engine._engine.dispose())
    engine._engine = None
    engine._session_factory = None
    url = f"sqlite+aiosqlite:///{tmp_path}/mnemos_gaps.db"
    monkeypatch.setenv("AION_DB_URL", url)
    monkeypatch.setenv("AION_MNEMOS_EMBEDDING_RECALL", "0")
    init_engine(url)
    import asyncio

    async def _create():
        async with get_async_session_maker()() as session:
            conn = await session.connection()
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    return url


@pytest.mark.anyio
async def test_hard_delete_invalidates_covering_digest(mnemos_db):
    scope = user_scope("default", "digest_leak")
    note = await store.insert_note(scope, content="Personal phone is +39 333 1234567")
    await store.insert_note(scope, content="Unrelated second note about the office")
    await store.upsert_digest(
        scope,
        0,
        2,
        "User shared the phone +39 333 1234567 and an office note",
        ready=True,
    )

    await store.forget_note(note.id, hard=True)

    digest = await store.get_digest(scope, 0, 2)
    assert digest is None or not digest.ready or not (digest.summary_text or "").strip()


@pytest.mark.anyio
async def test_recall_across_scopes_does_not_starve_later_scopes(mnemos_db):
    user = user_scope("default", "starve")
    project = project_scope("default", "starve")
    for i in range(12):
        await store.insert_note(
            user, content=f"User note {i} about deploy in a general context"
        )
    await store.insert_note(
        project, content="Project deploy target is namespace alibr-prod"
    )

    rows = await recall_across_scopes(
        [user, project], "deploy target namespace", limit=10
    )

    assert any("alibr-prod" in r["content"] for r in rows)


def test_default_fts_query_drops_stopwords():
    queries = build_fts_queries("what is the port of the metrics exporter")
    joined = " ".join(queries).lower()
    for stopword in ('"the"', '"is"', '"of"'):
        assert stopword not in joined, f"{stopword} must not become a search term"
