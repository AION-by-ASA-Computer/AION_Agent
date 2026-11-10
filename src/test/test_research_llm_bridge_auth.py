"""Deep Research LLM bridge: credentials, fail-fast probe and streaming.

Covers:
- the chat agent and the research bridge use the key of the provider they call
  (the chat used to pair the DB provider's URL/model with AION_LLM_API_KEY);
- the probe fails fast with the router's reason instead of "completing" a job
  with an empty report;
- completions are streamed, so a gateway that closes silent requests after 60 s
  (HTTP 504) no longer kills the final report, and reasoning deltas never leak
  into the text.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.research import llm_bridge

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _install_router(monkeypatch, key: str, handler) -> list:
    """Point the bridge at a fake router served by ``handler``; return the request log."""
    seen: list = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(_wrapped)
    monkeypatch.setattr(
        "src.runtime.llm_adapter.resolve_llm_credentials",
        lambda: ("https://router.example/api/v1", "openai/m1", key),
    )
    monkeypatch.setattr(
        llm_bridge.httpx,
        "AsyncClient",
        lambda *a, **k: _REAL_ASYNC_CLIENT(
            transport=transport, timeout=k.get("timeout")
        ),
    )
    monkeypatch.delenv("AION_LLM_ADAPTER", raising=False)
    # A different .env key must never be sent instead of the provider key.
    monkeypatch.setenv("AION_LLM_API_KEY", "placeholder-token")
    return seen


def _sse(*events: dict) -> httpx.Response:
    """An OpenAI-style SSE streaming response made of ``events``."""
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def _key_scoped(request: httpx.Request) -> httpx.Response:
    """Router that only lets ``Bearer db-key`` use the model."""
    if request.headers.get("authorization") != "Bearer db-key":
        return httpx.Response(
            404, json={"detail": "Model 'm1' is not allowed for this API key"}
        )
    return _sse(
        {"choices": [{"delta": {"reasoning_content": "hidden thinking"}}]},
        {"choices": [{"delta": {"content": "## Report\n"}}]},
        {"choices": [{"delta": {"content": "body"}}]},
    )


@pytest.mark.anyio
async def test_bridge_streams_with_provider_key(monkeypatch):
    """Provider key sent once, stream requested, only content deltas returned."""
    seen = _install_router(monkeypatch, "db-key", _key_scoped)
    out = await llm_bridge.complete_messages([{"role": "user", "content": "x"}])
    assert out == "## Report\nbody"
    assert [r.headers["authorization"] for r in seen] == ["Bearer db-key"]
    assert json.loads(seen[0].content)["stream"] is True


@pytest.mark.anyio
async def test_bridge_accepts_non_streamed_json(monkeypatch):
    """A server that ignores stream=true and answers JSON still works."""
    _install_router(
        monkeypatch,
        "db-key",
        lambda _r: httpx.Response(
            200, json={"choices": [{"message": {"content": "plain"}}]}
        ),
    )
    assert (
        await llm_bridge.complete_messages([{"role": "user", "content": "x"}])
        == "plain"
    )


@pytest.mark.anyio
async def test_bridge_stream_can_be_disabled(monkeypatch):
    """AION_DEEP_RESEARCH_LLM_STREAM=0 sends a classic non-streamed request."""
    seen = _install_router(
        monkeypatch,
        "db-key",
        lambda _r: httpx.Response(
            200, json={"choices": [{"message": {"content": "plain"}}]}
        ),
    )
    monkeypatch.setenv("AION_DEEP_RESEARCH_LLM_STREAM", "0")
    assert (
        await llm_bridge.complete_messages([{"role": "user", "content": "x"}])
        == "plain"
    )
    assert "stream" not in json.loads(seen[0].content)


@pytest.mark.anyio
async def test_bridge_caps_reasoning_and_retries_without_it(monkeypatch):
    """thinking_token_budget is sent on top of max_tokens and dropped on a 400 rejection."""

    def _strict(request: httpx.Request) -> httpx.Response:
        if "thinking_token_budget" in json.loads(request.content):
            return httpx.Response(400, json={"error": "unknown field"})
        return _sse({"choices": [{"delta": {"content": "ok"}}]})

    seen = _install_router(monkeypatch, "db-key", _strict)
    monkeypatch.setenv("AION_DEEP_RESEARCH_THINKING_BUDGET", "512")
    out = await llm_bridge.complete_messages(
        [{"role": "user", "content": "x"}], max_tokens=1000
    )
    assert out == "ok"
    first, second = (json.loads(r.content) for r in seen)
    # Reasoning room is added, so a short call keeps its full answer budget.
    assert first["thinking_token_budget"] == 512
    assert first["max_tokens"] == 1512
    assert "thinking_token_budget" not in second
    assert second["max_tokens"] == 1512


@pytest.mark.anyio
async def test_bridge_retries_empty_length_answer_with_more_tokens(monkeypatch):
    """Empty content at finish=length (reasoning ate max_tokens) is retried once with more room."""
    calls = {"n": 0}

    def _reasoning_then_answer(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _sse(
                {"choices": [{"delta": {"reasoning_content": "long thinking"}}]},
                {"choices": [{"delta": {}, "finish_reason": "length"}]},
            )
        return _sse(
            {"choices": [{"delta": {"content": "extracted"}, "finish_reason": "stop"}]}
        )

    seen = _install_router(monkeypatch, "db-key", _reasoning_then_answer)
    monkeypatch.setenv("AION_DEEP_RESEARCH_THINKING_BUDGET", "512")
    monkeypatch.setenv("AION_DEEP_RESEARCH_LENGTH_RETRY_TOKENS", "8192")
    out = await llm_bridge.complete_messages(
        [{"role": "user", "content": "x"}], max_tokens=4096
    )
    assert out == "extracted"
    assert [json.loads(r.content)["max_tokens"] for r in seen] == [4608, 12800]


@pytest.mark.anyio
async def test_bridge_timeout_is_total_even_when_streaming(monkeypatch):
    """A stream that keeps going past ``timeout`` is cut: the call returns "" in time."""
    import asyncio
    import time

    async def _slow(_request: httpx.Request) -> httpx.Response:
        async def _body():
            for _ in range(
                50
            ):  # ~5 s of reasoning deltas, each well under any read timeout
                await asyncio.sleep(0.1)
                yield b'data: {"choices":[{"delta":{"reasoning_content":"x"}}]}\n\n'

        return httpx.Response(
            200, content=_body(), headers={"content-type": "text/event-stream"}
        )

    _install_router(monkeypatch, "db-key", _slow)
    started = time.monotonic()
    out = await llm_bridge.complete_messages(
        [{"role": "user", "content": "x"}], max_tokens=100, timeout=0.5
    )
    assert out == ""
    assert time.monotonic() - started < 3


@pytest.mark.anyio
async def test_bridge_no_retry_when_model_stops_empty(monkeypatch):
    """An empty answer with finish=stop is not retried (no lack of room)."""
    seen = _install_router(
        monkeypatch,
        "db-key",
        lambda _r: _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
    )
    assert await llm_bridge.complete_messages([{"role": "user", "content": "x"}]) == ""
    assert len(seen) == 1


@pytest.mark.anyio
async def test_bridge_thinking_budget_can_be_disabled(monkeypatch):
    """AION_DEEP_RESEARCH_THINKING_BUDGET=0 sends neither the field nor extra tokens."""
    seen = _install_router(
        monkeypatch,
        "db-key",
        lambda _r: _sse({"choices": [{"delta": {"content": "ok"}}]}),
    )
    monkeypatch.setenv("AION_DEEP_RESEARCH_THINKING_BUDGET", "0")
    await llm_bridge.complete_messages(
        [{"role": "user", "content": "x"}], max_tokens=20
    )
    body = json.loads(seen[0].content)
    assert "thinking_token_budget" not in body
    assert body["max_tokens"] == 20


@pytest.mark.anyio
async def test_probe_raises_with_router_reason(monkeypatch):
    """A rejected key fails the probe with the endpoint's reason in the message."""
    seen = _install_router(monkeypatch, "wrong-key", _key_scoped)
    with pytest.raises(httpx.HTTPStatusError, match="not allowed for this API key"):
        await llm_bridge.probe_model()
    assert [r.headers["authorization"] for r in seen] == ["Bearer wrong-key"]
    # Regular calls still swallow errors so one failure does not abort a round.
    assert await llm_bridge.complete_messages([{"role": "user", "content": "x"}]) == ""


def test_chat_agent_resolves_key_with_url_and_model():
    """src.main builds the default generator from resolve_llm_credentials (URL+model+key)."""
    import inspect

    import src.main as main_mod

    src = inspect.getsource(main_mod._finish_get_agent_build)
    assert "resolve_llm_credentials()" in src
    assert "Secret.from_token(llm_api_key" in src
