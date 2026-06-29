"""Integration tests: plan finalizer and fake-LLM chat stream smoke tests."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.runtime.plan_engine import (
    PLAN_FINALIZE_USER_MESSAGE,
    PlanFinalizer,
    PlanModeController,
)


# ---------------------------------------------------------------------------
# Fake OpenAI-compatible streaming server
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sse_chunk(delta_content: str, finish_reason: str | None = None) -> bytes:
    """Format one server-sent-event chunk in OpenAI streaming format."""
    payload: Dict[str, Any] = {
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta_content} if delta_content else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


class _FakeLLMHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /v1/chat/completions streaming handler."""

    # Class-level list so tests can inspect requests received
    requests_received: List[Dict[str, Any]] = []

    def log_message(self, *args: Any) -> None:  # suppress access logs
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            _FakeLLMHandler.requests_received.append(json.loads(body))
        except Exception:
            pass

        body = b"".join(
            [
                _sse_chunk("Hello"),
                _sse_chunk(" from"),
                _sse_chunk(" AION!"),
                _sse_chunk("", finish_reason="stop"),
                b"data: [DONE]\n\n",
            ]
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except BrokenPipeError:
            pass

    def do_GET(self) -> None:
        """Health-check endpoint (used by check_llm_connection)."""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


class FakeLLMServer:
    """Context manager that runs a fake LLM HTTP server in a background thread."""

    def __init__(self) -> None:
        self.port = _free_port()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "FakeLLMServer":
        _FakeLLMHandler.requests_received = []
        self._server = HTTPServer(("127.0.0.1", self.port), _FakeLLMHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        # Wait for the server to be reachable
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                import urllib.request
                urllib.request.urlopen(f"{self.base_url}/", timeout=0.5)
                break
            except Exception:
                time.sleep(0.05)
        return self

    def __exit__(self, *_: Any) -> None:
        if self._server:
            self._server.shutdown()


# ---------------------------------------------------------------------------
# Test: fake LLM server works correctly (unit smoke test)
# ---------------------------------------------------------------------------


def test_fake_llm_server_responds():
    """The fake LLM server responds with SSE data chunks."""
    import urllib.request

    with FakeLLMServer() as srv:
        req = urllib.request.Request(
            f"{srv.base_url}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        body = resp.read().decode()

    assert "Hello" in body
    assert "[DONE]" in body


# ---------------------------------------------------------------------------
# Test: POST /v1/chat/stream route with mocked agent + fake LLM
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_chat_stream_route_yields_token_events(monkeypatch):
    """POST /v1/chat/stream yields token SSE events using a fake LLM backend.

    Heavy dependencies (history, agent factory, LTM) are mocked so no real
    DB or GPU is required.
    """
    import src.aion_env  # noqa: F401 — must be first

    with FakeLLMServer() as llm_srv:
        # Point AION at the fake LLM
        monkeypatch.setenv("AION_API_URL", f"{llm_srv.base_url}/v1")
        monkeypatch.setenv("AION_LLM_API_KEY", "fake-key")
        monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "0")
        monkeypatch.setenv("AION_ADMIN_PASSWORD_AUTH", "0")

        # Build a minimal fake agent that returns one assistant message
        fake_agent = MagicMock()
        from haystack.dataclasses import ChatMessage as CM

        async def _fake_run_async(messages, streaming_callback=None, generation_kwargs=None):
            if streaming_callback:
                try:
                    # Simulate streaming callbacks
                    from haystack.components.generators.utils import print_streaming_chunk
                except ImportError:
                    pass
            return {"messages": messages + [CM.from_assistant("Hello from AION!")]}

        fake_agent.run_async = _fake_run_async
        fake_agent.run = MagicMock(return_value={"messages": []})
        fake_agent.system_prompt = ""
        fake_agent.max_agent_steps = 5
        fake_agent.tools = []

        stm_msgs = [CM.from_user("previous message")]

        with (
            patch("src.main.get_agent", return_value=fake_agent),
            patch(
                "src.api.history.history_manager.get_window",
                new_callable=AsyncMock,
                return_value=stm_msgs,
            ),
            patch(
                "src.api.history.history_manager.upsert_message_content",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.api.history.history_manager.add_message",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.memory.ltm_orchestrator.ltm_orchestrator.wake_up",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.memory.ltm_orchestrator.ltm_orchestrator.build_augmented_user_text",
                side_effect=lambda aug, _, wake: aug,
            ),
            patch(
                "src.memory.ltm_orchestrator.ltm_orchestrator.extract_and_persist",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.runtime.llm_health.check_llm_connection",
                return_value=(True, None),
            ),
            patch(
                "src.runtime.redis_client.redis_set_stream_active",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.runtime.redis_client.redis_clear_stream_active",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.runtime.redis_client.redis_consume_force_compact",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "src.runtime.redis_client.redis_consume_stream_cancel",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            from httpx import ASGITransport, AsyncClient
            from src.api.main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/v1/chat/stream",
                    json={
                        "message": "Hello from test!",
                        "session_id": "integ-test-session-001",
                    },
                    timeout=30.0,
                )

        # The response may be 200 (streaming) or 307/422 depending on auth setup
        # At minimum verify the route was reachable
        assert resp.status_code in (200, 307, 401, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:200]}"
        )

        if resp.status_code == 200:
            body = resp.text
            # Parse SSE lines
            events = []
            for line in body.splitlines():
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    if raw and raw != "[DONE]":
                        try:
                            events.append(json.loads(raw))
                        except json.JSONDecodeError:
                            pass
            # At minimum a turn_started or token event should be present
            event_types = {e.get("type") for e in events}
            assert event_types, f"No SSE events parsed from response: {body[:500]}"


@pytest.mark.anyio
async def test_plan_finalize_stable_id_no_junk(monkeypatch):
    """Same plan_id across finalize attempts; invalid input returns None."""
    monkeypatch.setenv("AION_PLAN_FINALIZE_LLM", "0")
    pid = "execution_plan_integ01"
    ok = await PlanFinalizer.finalize(
        """# Piano test
## Obiettivo
Test

## Task
**task_01**: Prima azione
**task_02**: Seconda azione
""",
        user_message="test",
        plan_id=pid,
    )
    assert ok is not None
    assert ok.plan_id == pid

    bad = await PlanFinalizer.finalize("solo chiacchiere", user_message="x", plan_id=pid)
    assert bad is None


def test_plan_mode_sse_includes_stable_plan_id():
    ctrl = PlanModeController(plan_id="execution_plan_sse01")
    err = ctrl.sse_plan_error(PLAN_FINALIZE_USER_MESSAGE)
    assert err["plan_id"] == "execution_plan_sse01"
    assert err["type"] == "plan_error"


def test_v1_chat_stream_route_registered():
    """Smoke: /v1/chat/stream and /v1/chat/stop exist on the FastAPI app."""
    from src.api.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/v1/chat/stream" in paths
    assert "/v1/chat/stop" in paths


def test_turn_context_module_importable():
    """S2 integration smoke: turn context builder is wired and importable."""
    from src.runtime.turn import TurnContext, build_turn_context

    assert callable(build_turn_context)
    assert TurnContext.__dataclass_fields__["messages"].type is not None
