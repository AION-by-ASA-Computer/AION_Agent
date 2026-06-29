"""Research handler schedules background jobs from agent worker threads."""

import asyncio
import threading

import pytest

from src.main import set_event_loop
from src.research.handler import ResearchHandler, deep_research_enabled


@pytest.mark.anyio
async def test_start_research_from_worker_thread_uses_main_loop(monkeypatch):
    if not deep_research_enabled():
        pytest.skip("deep research disabled")

    async def _fake_run(*_a, **_k):
        return "ok"

    monkeypatch.setattr("src.research.handler.ResearchHandler._run_research", _fake_run)

    handler = ResearchHandler()
    main_loop = asyncio.get_running_loop()
    set_event_loop(main_loop)
    started = threading.Event()
    errors: list[str] = []

    def worker():
        try:
            handler.start_research("rp-test-thread", "LoRA fine-tuning", owner="u1")
            started.set()
        except Exception as e:
            errors.append(str(e))

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)
    assert not errors, errors
    assert started.is_set()
    entry = handler._active_tasks.get("rp-test-thread")
    assert entry is not None
    assert entry.get("task") is not None or entry.get("future") is not None
    handler.cancel_research("rp-test-thread")
