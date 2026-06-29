"""MCP warm fast-path and failure circuit breaker."""

import asyncio

from src.mcp_manager import BOOTSTRAP_SESSION_ID, MCPManager, MCPStdioWorker


def test_warm_skips_already_healthy_worker(monkeypatch):
    monkeypatch.setenv("AION_MCP_POOL", "1")

    async def _run():
        mgr = MCPManager()
        sid = "conv-1"
        mgr._session_ctx[sid] = ("generic_assistant", "demo", "default")

        key = mgr._resolve_pool_key(sid, "memory")
        worker = MCPStdioWorker(mgr, "memory", "")
        worker._task = asyncio.create_task(asyncio.sleep(3600))
        worker._ready.set()
        worker._init_error = None
        mgr._pool[key] = worker

        calls = {"n": 0}
        orig_get = mgr._get_worker

        async def _spy_get(*args, **kwargs):
            calls["n"] += 1
            return await orig_get(*args, **kwargs)

        monkeypatch.setattr(mgr, "_get_worker", _spy_get)
        await mgr.warm_session(
            sid, ["memory"], profile_slug="generic_assistant", user_id="demo"
        )
        worker._task.cancel()
        try:
            await worker._task
        except asyncio.CancelledError:
            pass
        assert calls["n"] == 0

    asyncio.run(_run())


def test_warm_circuit_skips_retry(monkeypatch):
    monkeypatch.setenv("AION_MCP_POOL", "1")
    monkeypatch.setenv("AION_MCP_WARM_FAIL_COOLDOWN_SEC", "600")

    async def _run():
        mgr = MCPManager()
        sid = "conv-2"
        mgr._session_ctx[sid] = ("generic_assistant", "demo", "default")
        pool_sid = mgr._resolve_pool_key(sid, "clickup-mcp")[0]
        mgr._record_warm_failure(pool_sid, "clickup-mcp", "401 Unauthorized")

        calls = {"n": 0}
        orig_get = mgr._get_worker

        async def _spy_get(*args, **kwargs):
            calls["n"] += 1
            return await orig_get(*args, **kwargs)

        monkeypatch.setattr(mgr, "_get_worker", _spy_get)
        await mgr.warm_session(
            sid, ["clickup-mcp"], profile_slug="generic_assistant", user_id="demo"
        )
        assert calls["n"] == 0
        assert mgr._warm_circuit_open(pool_sid, "clickup-mcp")

    asyncio.run(_run())


def test_worker_start_respects_circuit(monkeypatch):
    monkeypatch.setenv("AION_MCP_WARM_FAIL_COOLDOWN_SEC", "600")
    monkeypatch.setenv("AION_MCP_USER_POOL", "1")

    async def _run():
        mgr = MCPManager()
        mgr._session_ctx[BOOTSTRAP_SESSION_ID] = (
            "generic_assistant",
            "demo",
            "default",
        )
        mgr._record_warm_failure("__user__demo__default", "bad-mcp", "failed once")
        worker = MCPStdioWorker(mgr, "bad-mcp", "")
        worker._init_error = RuntimeError("failed once")
        worker._ready.set()
        worker._task = None
        await worker.start()
        assert worker._task is None

    asyncio.run(_run())
