"""Tests for Mnemos hybrid embedding recall."""

from __future__ import annotations

import pytest

from src.data.engine import get_async_session_maker, init_engine
from src.data.models import Base
from src.memory.mnemos import store
from src.memory.mnemos.embedding import reciprocal_rank_fusion
from src.memory.mnemos.recall import recall
from src.memory.mnemos.scope import user_scope


@pytest.fixture()
def mnemos_db(monkeypatch, tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/mnemos_hybrid.db"
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


def test_rrf_merge_prefers_overlap():
    fused = reciprocal_rank_fusion([[10, 20, 30], [20, 40]])
    assert fused[0][0] == 20


@pytest.mark.asyncio
async def test_recall_fts_fallback_without_embedding_service(mnemos_db, monkeypatch):
    monkeypatch.setenv("AION_MNEMOS_EMBEDDING_RECALL", "1")
    monkeypatch.delenv("AION_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("AION_EMBEDDING_URL", raising=False)

    scope = user_scope("default", "hybrid_fallback")
    await store.insert_note(scope, content="PostgreSQL is the preferred analytics database")
    rows = await recall(scope, "PostgreSQL analytics", limit=3)
    assert rows
    assert "PostgreSQL" in rows[0]["content"]


@pytest.mark.asyncio
async def test_recall_hybrid_with_mock_embedding(mnemos_db, monkeypatch):
    import numpy as np

    monkeypatch.setenv("AION_MNEMOS_EMBEDDING_RECALL", "1")
    monkeypatch.setenv("AION_EMBEDDING_MODEL", "mock")
    monkeypatch.setenv("AION_EMBEDDING_URL", "http://mock/embeddings")

    def _fake_embed(text: str):
        if "deploy" in text.lower() or "sunday" in text.lower():
            return np.array([1.0, 0.0], dtype=np.float32)
        if "coffee" in text.lower():
            return np.array([0.0, 1.0], dtype=np.float32)
        return np.array([0.5, 0.5], dtype=np.float32)

    monkeypatch.setattr("src.memory.mnemos.embedding.get_embedding", _fake_embed)

    scope = user_scope("default", "hybrid_mock")
    await store.insert_note(
        scope,
        content="Production deploy window is Sunday 02:00 UTC",
    )
    await store.insert_note(scope, content="Coffee machine is on floor two")

    rows = await recall(scope, "when can we deploy to production", limit=2)
    assert rows
    assert "Sunday" in rows[0]["content"]
