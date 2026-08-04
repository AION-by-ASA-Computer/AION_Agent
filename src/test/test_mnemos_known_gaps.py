"""Tripwires for Mnemos defects found by the adversarial benchmark.

Each test asserts the *desired* behaviour and is marked ``xfail(strict=True)``
while the defect is open. When a fix lands the test starts passing, strict mode
turns the unexpected pass into a failure, and whoever fixed it must remove the
marker. That keeps the list of known gaps honest instead of letting it rot.

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


@pytest.mark.xfail(
    strict=True,
    reason="forget_note(hard=True) deletes the row and the FTS entry but never "
    "invalidates digests covering it, so the content survives in "
    "ltm_digests.summary_text and keeps reaching the model through wake",
)
@pytest.mark.asyncio
async def test_hard_delete_invalidates_covering_digest(mnemos_db):
    scope = user_scope("default", "digest_leak")
    note = await store.insert_note(scope, content="Personal phone is +39 333 1234567")
    await store.insert_note(scope, content="Unrelated second note about the office")
    await store.upsert_digest(
        scope, 0, 2, "User shared the phone +39 333 1234567 and an office note", ready=True
    )

    await store.forget_note(note.id, hard=True)

    digest = await store.get_digest(scope, 0, 2)
    assert digest is None or not digest.ready, (
        "a digest covering a hard-deleted note must be invalidated"
    )


@pytest.mark.xfail(
    strict=True,
    reason="recall_across_scopes fills the result list scope by scope and returns "
    "as soon as the limit is reached, so a crowded user scope hides project "
    "notes entirely; scores are never normalised across scopes",
)
@pytest.mark.asyncio
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

    rows = await recall_across_scopes([user, project], "deploy target namespace", limit=10)

    assert any("alibr-prod" in r["content"] for r in rows), (
        "the project note must be reachable even when the user scope is crowded"
    )


@pytest.mark.xfail(
    strict=True,
    reason="the default FTS path (AION_MNEMOS_FTS_PHRASE_QUERY=0) ORs every token "
    "of two characters or more with no stopword filtering, so any note "
    "sharing an article with the query is returned as a match",
)
def test_default_fts_query_drops_stopwords():
    queries = build_fts_queries("what is the port of the metrics exporter")
    joined = " ".join(queries).lower()
    for stopword in ('"the"', '"is"', '"of"'):
        assert stopword not in joined, f"{stopword} must not become a search term"
