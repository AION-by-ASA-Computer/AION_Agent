"""Proxy LLM enterprise: /v1/llm/models e /v1/llm/chat/completions."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.api.v1 import llm_proxy

SECRET = "sk-super-secret"
BASE = "https://llm.internal.example/v1"


def _row(slug="gpt-x", **kw):
    base = dict(
        slug=slug,
        display_name="GPT X",
        description="desc",
        provider="openai",
        model_name="upstream-model",
        api_base_url=BASE,
        api_key_encrypted="enc",
        timeout=30,
        max_chat_tokens=1000,
        enabled=True,
        is_default=True,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def env(monkeypatch):
    state = {"rows": {"gpt-x": _row()}, "seen": [], "handler": None}

    async def tenant(_auth):
        return "default"

    async def list_enabled(_t):
        return [r for r in state["rows"].values() if r.enabled]

    async def get_enabled(_t, slug):
        r = state["rows"].get(slug)
        return r if r and r.enabled else None

    def make_client(timeout):
        def handler(request: httpx.Request):
            state["seen"].append(request)
            return state["handler"](request)

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(llm_proxy, "_resolve_tenant_id", tenant)
    monkeypatch.setattr(llm_proxy, "_list_enabled", list_enabled)
    monkeypatch.setattr(llm_proxy, "_get_enabled", get_enabled)
    monkeypatch.setattr(llm_proxy, "_make_client", make_client)
    monkeypatch.setattr(llm_proxy, "decrypt_value", lambda _v: SECRET)

    app = FastAPI()
    app.include_router(llm_proxy.router, prefix="/v1")
    app.dependency_overrides[require_chat_auth] = lambda: ChatAuthIdentity()
    state["app"] = app
    with TestClient(app) as c:
        state["client"] = c
        yield state


def _post(env, **body):
    body.setdefault("model", "gpt-x")
    body.setdefault("messages", [{"role": "user", "content": "hi"}])
    return env["client"].post("/v1/llm/chat/completions", json=body)


def test_models_list_hides_secrets(env):
    env["rows"]["off"] = _row("off", enabled=False)
    r = env["client"].get("/v1/llm/models")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert [m["id"] for m in body["data"]] == ["gpt-x"]
    m = body["data"][0]
    assert m["owned_by"] == "aion" and m["model_name"] == "upstream-model"
    assert m["is_default"] is True
    text = r.text
    assert SECRET not in text and "llm.internal" not in text and "enc" not in m


def test_unknown_and_disabled_slug_404(env):
    env["rows"]["off"] = _row("off", enabled=False)
    for slug in ("nope", "off"):
        r = _post(env, model=slug)
        assert r.status_code == 404
        err = r.json()["error"]
        assert err["code"] == "model_not_found"
        assert err["type"] == "invalid_request_error"
    assert env["seen"] == []


def test_non_stream_passthrough_with_tools(env):
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]

    def handler(req):
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "model": "upstream-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [{"id": "t1", "type": "function"}],
                        }
                    }
                ],
            },
        )

    env["handler"] = handler
    r = _post(
        env,
        tools=tools,
        tool_choice="auto",
        temperature=0.2,
        top_p=0.9,
        stop=["x"],
        response_format={"type": "json_object"},
        reasoning_effort="low",
        unknown_field="drop",
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["tool_calls"][0]["id"] == "t1"
    assert r.json()["model"] == "gpt-x"
    req = env["seen"][0]
    assert str(req.url) == BASE + "/chat/completions"
    assert req.headers["authorization"] == f"Bearer {SECRET}"
    sent = json.loads(req.content)
    assert sent["model"] == "upstream-model"
    assert sent["tools"] == tools and sent["tool_choice"] == "auto"
    assert sent["reasoning_effort"] == "low" and sent["stream"] is False
    assert "unknown_field" not in sent
    assert SECRET not in r.text


def test_stream_passthrough(env):
    sse = (
        'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    env["handler"] = lambda req: httpx.Response(
        200, content=sse.encode(), headers={"content-type": "text/event-stream"}
    )
    r = _post(env, stream=True)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text == sse
    assert json.loads(env["seen"][0].content)["stream"] is True


def test_max_tokens_capped(env):
    env["handler"] = lambda req: httpx.Response(200, json={"choices": []})
    _post(env, max_tokens=999999)
    assert json.loads(env["seen"][-1].content)["max_tokens"] == 1000
    _post(env, max_tokens=50)
    assert json.loads(env["seen"][-1].content)["max_tokens"] == 50


def test_upstream_429_translated(env):
    env["handler"] = lambda req: httpx.Response(
        429,
        json={"error": {"message": "slow down", "type": "x"}},
        headers={"retry-after": "7"},
    )
    r = _post(env)
    assert r.status_code == 429
    assert r.json()["error"]["message"] == "slow down"
    assert r.json()["error"]["type"] == "rate_limit_error"
    assert r.headers["retry-after"] == "7"


def test_upstream_401_becomes_502_and_stream_error_status(env):
    env["handler"] = lambda req: httpx.Response(401, json={"error": {"message": SECRET}})
    for stream in (False, True):
        r = _post(env, stream=stream)
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "upstream_auth_error"
        assert SECRET not in r.text


def test_unsupported_provider_501(env):
    env["rows"]["claude"] = _row(
        "claude", provider="anthropic", api_base_url="https://api.anthropic.com"
    )
    r = _post(env, model="claude")
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "provider_not_supported"
    assert env["seen"] == []


def test_validation_errors(env):
    r = env["client"].post("/v1/llm/chat/completions", json={"messages": []})
    assert r.status_code == 400
    r = env["client"].post("/v1/llm/chat/completions", json={"model": "gpt-x"})
    assert r.status_code == 400


def test_auth_required(monkeypatch, env):
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    env["app"].dependency_overrides.clear()
    assert env["client"].get("/v1/llm/models").status_code == 401
    r = env["client"].post(
        "/v1/llm/chat/completions",
        json={"model": "gpt-x", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 401
    assert env["seen"] == []
