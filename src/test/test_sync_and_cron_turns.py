"""POST /v1/chat e cron runner: flag di cancel, grafici e anteprima (FIX-04/05/06)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

import src.api.v1.chat as chat
import src.runtime.cron_runner as cron_runner
from src.api.auth_login import ChatAuthIdentity
from src.chart_queue import chart_queue
from src.runtime import cron_db
from src.test.test_api_endpoints import _reset_unified_db

CHART = {"query": "up", "data": [[1, 2]]}


@pytest.mark.anyio
async def test_chat_sync_clears_cancel_flag_and_returns_charts(monkeypatch) -> None:
    calls: List[str] = []

    async def fake_clear_cancel(cid: str) -> None:
        calls.append(f"clear:{cid}")

    class FakePipeline:
        def __init__(self, **kw: Any) -> None:
            self.session_id = kw["session_id"]

        async def run(self, message: str, **_kw: Any) -> Dict[str, Any]:
            calls.append("run")
            chart_queue.push_serialized(self.session_id, CHART)
            return {"text": "ok", "success": True, "charts": []}

    async def fake_get_agent(profile: str, **_kw: Any):
        return object(), profile

    async def passthrough_profile(_row_id, profile):
        return profile

    async def noop(*_a, **_k):
        return None

    monkeypatch.setenv("AION_UNIFIED_DB", "0")
    monkeypatch.delenv("AION_REDIS_URL", raising=False)
    monkeypatch.setattr(chat, "redis_clear_stream_cancel", fake_clear_cancel)
    monkeypatch.setattr(chat, "_resolve_chat_user_id", lambda *_a, **_k: "u1")
    monkeypatch.setattr(chat, "enforce_profile_access", passthrough_profile)
    monkeypatch.setattr(chat, "claim_conversation_for_write", noop)
    monkeypatch.setattr(chat, "_clamped_runtime", noop)
    monkeypatch.setattr(chat, "get_agent", fake_get_agent)
    monkeypatch.setattr(chat, "AgentPipeline", FakePipeline)

    body = chat.ChatSyncBody(message="hi", conversation_id="sync-conv-1")
    out = await chat.chat_sync(body, auth=ChatAuthIdentity(), x_aion_user_id=None)

    assert calls == ["clear:sync-conv-1", "run"]
    assert out.text == "ok"
    assert [(c["query"], c["data"]) for c in out.charts] == [("up", [[1, 2]])]
    assert chart_queue.get_serialized("sync-conv-1") == []


@pytest.mark.anyio
async def test_cron_run_stops_previous_turn_and_previews_final_text(
    monkeypatch, tmp_path: Path
) -> None:
    await _reset_unified_db(monkeypatch, tmp_path)
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_engine

    await ensure_bootstrap_schema(get_engine())
    job = await cron_db.create_job(
        user_id="u1",
        name="Report",
        cron_expression="0 9 * * *",
        prompt="ping",
        profile_slug="generic_assistant",
        session_mode="fixed",
        session_id="cron-conv-1",
        created_by="test",
    )

    calls: List[str] = []

    async def fake_stop(cid: str, *, timeout: float = 30.0) -> None:
        calls.append(f"stop:{cid}")

    async def fake_clear_cancel(cid: str) -> None:
        calls.append(f"clear:{cid}")

    async def fake_set_active(cid: str, **_kw: Any) -> None:
        calls.append(f"active:{cid}")

    async def fake_clear_active(_cid: str) -> None:
        return None

    class FakePipeline:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def run_stream(self, prompt: str, **_kw: Any):
            for tok in ("<think>", "draft"):
                yield {"type": "token", "content": tok}
            yield {"type": "final", "text": "Final answer"}

    async def fake_get_agent(profile: str, **_kw: Any):
        return object(), profile

    monkeypatch.setattr(chat, "_stop_background_run", fake_stop)
    monkeypatch.setattr(cron_runner, "redis_clear_stream_cancel", fake_clear_cancel)
    monkeypatch.setattr(cron_runner, "redis_set_stream_active", fake_set_active)
    monkeypatch.setattr(cron_runner, "redis_clear_stream_active", fake_clear_active)
    monkeypatch.setattr(cron_runner, "get_agent", fake_get_agent)
    monkeypatch.setattr(cron_runner, "AgentPipeline", FakePipeline)

    out = await cron_runner.execute_job(job["job_id"], trigger="manual")

    assert out["ok"] is True
    assert calls == ["stop:cron-conv-1", "clear:cron-conv-1", "active:cron-conv-1"]
    runs = await cron_db.list_runs(job["job_id"])
    assert runs[0]["assistant_preview"] == "Final answer"
    assert "cron-conv-1" not in chat._background_runs
    await cron_db.delete_job(job["job_id"])
