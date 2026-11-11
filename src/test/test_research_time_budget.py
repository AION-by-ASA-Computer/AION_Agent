"""Deep Research time budget: pages queued after max_time are skipped.

A slow reasoning model used to keep extracting every page of a round long past
the run's ``max_time`` budget (18 minutes of reading on a 5-minute budget), so
the job hit the 1800 s hard timeout before the final report. Pages already
being read finish; pages still waiting for a slot are skipped.
"""

from __future__ import annotations

import asyncio

import pytest

from src.research import deep_research as dr


@pytest.mark.anyio
async def test_queued_pages_skipped_after_time_budget(monkeypatch):
    """With concurrency 1 and the budget expiring during page 1, pages 2-4 are not read."""
    researcher = dr.DeepResearcher(
        llm_endpoint="", llm_model="m", extraction_concurrency=1, max_time=60
    )
    read: list[str] = []
    clock = {"now": 1000.0}
    monkeypatch.setattr(dr.time, "time", lambda: clock["now"])
    researcher._start_time = 1000.0

    async def _fake_search(query):
        return [{"url": f"https://p{i}.org", "title": f"P{i}"} for i in range(1, 5)]

    async def _fake_extract(url, question, title):
        read.append(url)
        clock["now"] += 120  # reading this page exhausts the 60 s budget
        await asyncio.sleep(0)
        return {"url": url, "findings": "f"}

    monkeypatch.setattr(researcher, "_search", _fake_search)
    monkeypatch.setattr(researcher, "_fetch_and_extract", _fake_extract)
    findings = await researcher._search_and_extract(["q"], "question")
    assert read == ["https://p1.org"]
    assert len(findings) == 1


def test_report_timeout_env(monkeypatch):
    """AION_DEEP_RESEARCH_REPORT_TIMEOUT sets the report deadline (min 60, default 600)."""
    monkeypatch.delenv("AION_DEEP_RESEARCH_REPORT_TIMEOUT", raising=False)
    assert dr._report_timeout() == 600
    monkeypatch.setenv("AION_DEEP_RESEARCH_REPORT_TIMEOUT", "900")
    assert dr._report_timeout() == 900
    monkeypatch.setenv("AION_DEEP_RESEARCH_REPORT_TIMEOUT", "10")
    assert dr._report_timeout() == 60
