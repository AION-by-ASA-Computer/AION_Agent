"""MCP warm fast-path and failure circuit breaker."""

import asyncio

from src.mcp_manager import BOOTSTRAP_SESSION_ID, MCPManager, MCPStdioWorker


def test_warm_skips_already_healthy_worker(monkeypatch):
    monkeypatch.setenv("AION_MCP_POOL", "1")

    async def _run():
        mgr = MCPManager()
        sid = "conv-1"
        mgr._session_ctx[sid] = ("generic_assistant", "demo", "default")

        key = mgr._resolve_pool_key(sid, "query_memory")
        worker = MCPStdioWorker(mgr, "query_memory", "")
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
            sid, ["query_memory"], profile_slug="generic_assistant", user_id="demo"
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


def _park(mgr: MCPManager, sid: str, name: str, stopped: list):
    worker = MCPStdioWorker(mgr, name, sid)
    worker._task = asyncio.create_task(asyncio.sleep(3600))
    worker._ready.set()

    async def _shutdown() -> None:
        stopped.append(name)
        if worker._task and not worker._task.done():
            worker._task.cancel()

    worker.shutdown = _shutdown  # type: ignore[method-assign]
    mgr._pool[(sid, name)] = worker
    return worker


def test_partial_warm_keeps_sibling_workers(monkeypatch):
    monkeypatch.setenv("AION_MCP_POOL", "1")

    async def _run():
        mgr = MCPManager()
        sid = "oai-keep"
        mgr._session_ctx[sid] = ("apple_agent", "admin", "default")
        stopped: list = []
        sandbox = _park(mgr, sid, "session_sandbox", stopped)
        skills = _park(mgr, sid, "skills_hub", stopped)
        monkeypatch.setattr(mgr, "_is_stdio_server", lambda _name: False)
        await mgr.warm_session(
            sid, ["outlook"], profile_slug="apple_agent", user_id="admin"
        )
        assert (sid, "session_sandbox") in mgr._pool
        assert (sid, "skills_hub") in mgr._pool
        assert stopped == []
        sandbox._task.cancel()
        skills._task.cancel()

    asyncio.run(_run())


def test_profile_switch_stops_only_servers_absent_from_new_profile(monkeypatch):
    monkeypatch.setenv("AION_MCP_POOL", "1")

    async def _run():
        mgr = MCPManager()
        sid = "chat-switch"
        mgr._session_ctx[sid] = ("apple_agent", "admin", "default")
        stopped: list = []
        sandbox = _park(mgr, sid, "session_sandbox", stopped)
        _park(mgr, sid, "clickup", stopped)
        monkeypatch.setattr(mgr, "_is_stdio_server", lambda _name: False)
        monkeypatch.setattr(
            mgr,
            "_profile_mcp_servers",
            lambda _slug: {"session_sandbox", "skills_hub"},
        )
        await mgr.warm_session(
            sid, ["skills_hub"], profile_slug="generic_assistant", user_id="admin"
        )
        assert stopped == ["clickup"]
        assert (sid, "session_sandbox") in mgr._pool
        assert (sid, "clickup") not in mgr._pool
        sandbox._task.cancel()

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
