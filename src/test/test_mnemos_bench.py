"""Tests for Mnemos bench runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.engine import get_async_session_maker, init_engine
from src.data.models import Base


@pytest.fixture()
def bench_db(monkeypatch, tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/mnemos_bench.db"
    monkeypatch.setenv("AION_DB_URL", url)
    monkeypatch.setenv("AION_BENCHMARK_DATA_DIR", str(tmp_path / "benchmarks"))
    init_engine(url)
    import asyncio

    async def _create():
        async with get_async_session_maker()() as session:
            conn = await session.connection()
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    return tmp_path


@pytest.mark.asyncio
async def test_mnemos_bench_smoke(bench_db, monkeypatch):
    from src.benchmarks.mnemos_bench.runner import run_mnemos_bench

    dataset = bench_db / "mini.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "mini",
                        "scope_type": "user",
                        "setup_notes": ["Token ZEBRA-99 for staging access"],
                        "query": "ZEBRA-99 staging",
                        "expected_substrings": ["ZEBRA-99"],
                        "recall_limit": 3,
                        "min_hits": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    metrics = await run_mnemos_bench(
        run_id="test_bench_run",
        dataset_path=str(dataset),
    )
    assert metrics["case_count"] == 1
    assert metrics["accuracy_overall"] == 1.0
