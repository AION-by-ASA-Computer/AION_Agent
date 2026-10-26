"""remote-bridge verso un broker FastMCP streamable HTTP con Bearer token (mcp-remote reale).

Richiede ``node`` e ``mcp-remote`` installato localmente (``node_modules/mcp-remote``,
come nell'immagine Docker) oppure ``AION_TEST_MCP_REMOTE_PROXY=/percorso/proxy.js``.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

import pytest

import src.mcp_manager as mm
from src.mcp_manager import MCPManager
from src.mcp_remote_install import (
    build_remote_bridge_registry_config,
    mcp_remote_proxy_path,
)

pytestmark = pytest.mark.integration

TOKEN = "broker-test-token"


def _proxy_path() -> Optional[str]:
    explicit = os.getenv("AION_TEST_MCP_REMOTE_PROXY", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    return mcp_remote_proxy_path()


PROXY = _proxy_path()
if not shutil.which("node") or not PROXY:
    pytest.skip("node o mcp-remote locale non disponibili", allow_module_level=True)


def _free_port(host: str) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _lan_ip() -> Optional[str]:
    """IP non loopback della macchina, se esiste (nessun pacchetto inviato)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith("127.") else ip


def _broker_app() -> Any:
    from fastmcp import FastMCP

    mcp = FastMCP("broker")

    @mcp.tool
    def read_status(host: str = "web01") -> str:
        """Stato di un host (sola lettura)."""
        return f"{host}: ok"

    app = mcp.http_app(path="/mcp")

    async def guard(scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope.get("headers") or []).get(b"authorization")
            if auth != f"Bearer {TOKEN}".encode():
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await app(scope, receive, send)

    return guard


def _serve(host: str) -> Iterator[str]:
    import uvicorn

    port = _free_port(host)
    server = uvicorn.Server(
        uvicorn.Config(_broker_app(), host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "broker FastMCP non avviato"
    try:
        yield f"http://{host}:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="module")
def broker_url() -> Iterator[str]:
    yield from _serve("127.0.0.1")


@pytest.fixture(scope="module")
def lan_broker_url() -> Iterator[str]:
    ip = _lan_ip()
    if not ip:
        pytest.skip("nessun IP non loopback disponibile")
    yield from _serve(ip)


def _manager(
    monkeypatch: pytest.MonkeyPatch, cfg: Dict[str, Any], token: Optional[str]
) -> tuple[MCPManager, List[Any]]:
    """MCPManager con la voce ``broker`` e il token org_shared risolto (o assente)."""
    import src.runtime.credential_store as cs

    async def fake_resolve(env_block, **_k):
        return {"API_KEY": token} if token else {}

    spawned: List[Any] = []
    real_stdio_client = mm.stdio_client

    def spy_stdio_client(params):
        spawned.append(params)
        return real_stdio_client(params)

    mgr = MCPManager()
    monkeypatch.setattr(mgr, "load_registry", lambda **_k: None)
    monkeypatch.setattr(mgr, "get_server_config", lambda name: dict(cfg))
    monkeypatch.setattr("src.mcp_remote_install.mcp_remote_proxy_path", lambda: PROXY)
    monkeypatch.setattr(cs, "resolve_mcp_env_for_user", fake_resolve)
    monkeypatch.setattr(mm, "_apply_mcp_home_isolation", lambda env, uid: None)
    monkeypatch.setattr(mm, "stdio_client", spy_stdio_client)
    monkeypatch.setenv("AION_MCP_INIT_TIMEOUT", "20")
    return mgr, spawned


def _broker_cfg(url: str, **extra: Any) -> Dict[str, Any]:
    cfg = build_remote_bridge_registry_config(
        url, "broker", auth_type="api-key", credential_mode="org_shared"
    )
    cfg.update(extra)
    return cfg


async def _list_and_call(mgr: MCPManager) -> tuple[List[str], str]:
    async with mgr.session_context("broker") as session:
        tools = await session.list_tools()
        res = await session.call_tool("read_status", {"host": "db01"})
        return [t.name for t in tools.tools], res.content[0].text


def test_correct_token_lists_and_calls_tools(monkeypatch, broker_url) -> None:
    mgr, spawned = _manager(monkeypatch, _broker_cfg(broker_url), TOKEN)
    names, text = asyncio.run(_list_and_call(mgr))
    assert names == ["read_status"]
    assert text == "db01: ok"
    assert spawned[0].env["API_KEY"] == TOKEN
    assert TOKEN not in " ".join(spawned[0].args)


def test_missing_token_blocks_spawn(monkeypatch, broker_url) -> None:
    mgr, spawned = _manager(monkeypatch, _broker_cfg(broker_url), None)
    with pytest.raises(RuntimeError, match="credenziali mancanti"):
        asyncio.run(_list_and_call(mgr))
    assert spawned == []


def test_wrong_token_fails_fast(monkeypatch, broker_url) -> None:
    """401 dal broker: mcp-remote termina senza restare in attesa del flusso OAuth."""
    mgr, spawned = _manager(monkeypatch, _broker_cfg(broker_url), "wrong-token")
    start = time.monotonic()
    with pytest.raises(BaseException) as exc:
        asyncio.run(_list_and_call(mgr))
    assert not isinstance(exc.value, KeyboardInterrupt)
    assert time.monotonic() - start < 15
    assert len(spawned) == 1


def test_lan_http_broker_needs_allow_http(monkeypatch, lan_broker_url) -> None:
    mgr, _ = _manager(monkeypatch, _broker_cfg(lan_broker_url), TOKEN)
    with pytest.raises(BaseException):
        asyncio.run(_list_and_call(mgr))

    mgr, _ = _manager(monkeypatch, _broker_cfg(lan_broker_url, allow_http=True), TOKEN)
    names, _text = asyncio.run(_list_and_call(mgr))
    assert names == ["read_status"]
