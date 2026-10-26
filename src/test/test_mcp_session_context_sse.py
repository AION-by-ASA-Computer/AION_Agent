"""session_context su server SSE: un solo client, uscita pulita, errori propagati."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import pytest

import src.mcp_manager as mm
from src.mcp_manager import MCPManager

SSE_CFG: Dict[str, Any] = {"type": "sse", "url": "http://broker.local/sse"}


class _FakeSession:
    def __init__(self, read: Any, write: Any) -> None:
        self.initialized = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def initialize(self) -> None:
        self.initialized = True

    async def list_tools(self) -> List[str]:
        return ["tool_a"]


def _setup(monkeypatch: pytest.MonkeyPatch) -> tuple[MCPManager, List[str]]:
    opened: List[str] = []

    @asynccontextmanager
    async def fake_sse_client(url: str, headers: Dict[str, str] | None = None):
        opened.append(url)
        yield (object(), object())

    class _NoToken:
        async def get_token(self) -> None:
            return None

    mgr = MCPManager()
    monkeypatch.setattr(mgr, "load_registry", lambda **_k: None)
    monkeypatch.setattr(mgr, "get_server_config", lambda name: dict(SSE_CFG))
    monkeypatch.setattr(mm, "sse_client", fake_sse_client)
    monkeypatch.setattr(mm, "ClientSession", _FakeSession)
    monkeypatch.setattr(mm, "khub_token_manager", _NoToken())
    return mgr, opened


def test_sse_session_context_opens_once_and_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr, opened = _setup(monkeypatch)

    async def run() -> List[str]:
        async with mgr.session_context("broker") as session:
            assert session.initialized
            return await session.list_tools()

    assert asyncio.run(run()) == ["tool_a"]
    assert opened == [SSE_CFG["url"]]
    assert mgr._active_servers.get("broker", 0) == 0


def test_sse_session_context_propagates_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr, opened = _setup(monkeypatch)

    async def run() -> None:
        async with mgr.session_context("broker"):
            raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(run())
    assert opened == [SSE_CFG["url"]]
    assert mgr._active_servers.get("broker", 0) == 0
