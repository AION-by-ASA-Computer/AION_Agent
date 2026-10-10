"""OpenAI-compatible facade: mapping helpers and HTTP contract."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.v1.openai_compat import (
    ChatCompletionBody,
    OpenAIMessage,
    build_user_input,
    derived_conversation_id,
    iter_stream_deltas,
    parse_messages,
    resolve_conversation_id,
    split_model,
)


def test_split_model_profile_and_provider():
    assert split_model("aion_std") == ("aion_std", None)
    assert split_model(" ops@local-llm ") == ("ops", "local-llm")
    assert split_model("ops@") == ("ops", None)


def test_parse_messages_flattens_parts_and_stops_at_last_user():
    parsed = parse_messages(
        [
            OpenAIMessage(role="system", content="be brief"),
            OpenAIMessage(
                role="user",
                content=[
                    {"type": "text", "text": "first"},
                    {"type": "image_url", "image_url": {}},
                ],
            ),
            OpenAIMessage(role="assistant", content="ack"),
            OpenAIMessage(role="user", content="second"),
            OpenAIMessage(role="assistant", content="prefill"),
        ]
    )
    assert parsed is not None
    assert parsed.systems == ["be brief"]
    assert parsed.first_user == "first"
    assert parsed.last_user == "second"
    assert parsed.transcript[-1] == ("user", "second")


def test_build_user_input_keeps_history_only_on_first_turn():
    parsed = parse_messages(
        [
            OpenAIMessage(role="developer", content="use Italian"),
            OpenAIMessage(role="user", content="ciao"),
            OpenAIMessage(role="assistant", content="pronto"),
            OpenAIMessage(role="user", content="continua"),
        ]
    )
    assert parsed is not None
    first = build_user_input(parsed, session_has_history=False)
    assert "use Italian" in first
    assert "User: ciao" in first
    assert first.endswith("continua")
    assert build_user_input(parsed, session_has_history=True) == "continua"


def test_single_user_message_is_unchanged():
    parsed = parse_messages([OpenAIMessage(role="user", content="hello")])
    assert parsed is not None
    assert build_user_input(parsed, session_has_history=False) == "hello"


def test_derived_conversation_id_is_stable_for_the_thread():
    a = derived_conversation_id("jane", "aion_std", "open with this")
    b = derived_conversation_id("jane", "aion_std", "open with this")
    c = derived_conversation_id("jane", "aion_std", "different chat")
    assert a == b
    assert a != c
    assert a.startswith("oai-")
    assert (
        resolve_conversation_id(
            header="sess-explicit-1",
            metadata=None,
            user_id="jane",
            model="aion_std",
            first_user_text="open with this",
        )
        == "sess-explicit-1"
    )


def test_stream_deltas_do_not_repeat_the_final_text():
    deltas = iter_stream_deltas(
        [
            {"type": "token", "content": "hel"},
            {"type": "token", "content": "lo"},
            {"type": "reasoning", "reasoning": "thinking"},
            {"type": "final", "text": "hello"},
        ]
    )
    contents = [d.get("content") for d in deltas if "content" in d]
    assert contents == ["hel", "lo"]
    assert deltas[0]["role"] == "assistant"
    assert any(d.get("reasoning_content") == "thinking" for d in deltas)


def test_stream_deltas_emit_final_when_no_tokens():
    deltas = iter_stream_deltas([{"type": "final", "text": "only final"}])
    assert deltas == [{"role": "assistant", "content": "only final"}]


class _FakePipeline:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def run(self, user_input, **kwargs):
        return {"text": f"echo:{user_input}", "success": True, "charts": []}

    async def run_stream(self, user_input, **kwargs):
        yield {"type": "tool_event", "event": {"name": "lookup"}}
        yield {"type": "token", "content": "hel"}
        yield {"type": "token", "content": "lo"}
        yield {"type": "final", "text": "hello"}


def _profile(name: str):
    return SimpleNamespace(slug=name, name=name, description=f"{name} desc")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "0")
    monkeypatch.setenv("AION_UNIFIED_DB", "0")

    profiles = [
        {"slug": "aion_std", "name": "AION Standard", "description": "default"},
        {"slug": "ops", "name": "Ops", "description": "ops profile"},
    ]

    async def profiles_for(_user_row_id):
        return profiles

    async def no_history(_session_id, _profile):
        return False

    async def ensure(*_args, **_kwargs):
        return None

    async def runtime(*_args, **_kwargs):
        return {}

    async def get_agent(profile, **kwargs):
        return object(), profile

    monkeypatch.setattr("src.api.v1.openai_compat._profiles_for", profiles_for)
    monkeypatch.setattr("src.api.v1.openai_compat._session_has_history", no_history)
    monkeypatch.setattr("src.api.v1.openai_compat._ensure_conversation", ensure)
    monkeypatch.setattr("src.api.v1.openai_compat._turn_runtime", runtime)
    monkeypatch.setattr("src.main.get_agent", get_agent)
    monkeypatch.setattr("src.agent_pipeline.AgentPipeline", _FakePipeline)
    monkeypatch.setattr(
        "src.agent_profile.profile_manager.get_profile",
        lambda name: (
            _profile(name.strip().lower())
            if name.strip().lower() in {"aion_std", "ops"}
            else None
        ),
    )

    from src.api.v1.openai_compat import router

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    with TestClient(app) as test_client:
        yield test_client


def test_list_models(client):
    response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert [item["id"] for item in body["data"]] == ["aion_std", "ops"]
    assert body["data"][0]["owned_by"] == "aion"


def test_unknown_model_does_not_fall_back(client, monkeypatch):
    called = {"n": 0}

    async def get_agent(*_args, **_kwargs):
        called["n"] += 1
        return object(), "aion_std"

    monkeypatch.setattr("src.main.get_agent", get_agent)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"
    assert called["n"] == 0


def test_completion_maps_model_to_profile_and_ignores_tools(client, monkeypatch):
    seen = {}

    async def get_agent(profile, **kwargs):
        seen["profile"] = profile
        seen["provider"] = kwargs.get("llm_provider_name")
        seen["session_id"] = kwargs.get("session_id")
        return object(), profile

    class RecordingPipeline(_FakePipeline):
        async def run(self, user_input, **kwargs):
            seen["user_input"] = user_input
            seen["metadata"] = kwargs.get("metadata")
            seen["reasoning_effort"] = kwargs.get("reasoning_effort")
            return await super().run(user_input, **kwargs)

    monkeypatch.setattr("src.main.get_agent", get_agent)
    monkeypatch.setattr("src.agent_pipeline.AgentPipeline", RecordingPipeline)

    response = client.post(
        "/v1/chat/completions",
        headers={"X-AION-Conversation-Id": "thread-1234"},
        json={
            "model": "ops@local-llm",
            "tools": [{"type": "function", "function": {"name": "remote_tool"}}],
            "messages": [
                {"role": "system", "content": "answer in Italian"},
                {"role": "user", "content": "stato"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "ops@local-llm"
    assert body["choices"][0]["message"]["content"].startswith("echo:")
    assert "answer in Italian" in body["choices"][0]["message"]["content"]
    assert "remote_tool" not in body["choices"][0]["message"]["content"]
    assert body["aion_conversation_id"] == "thread-1234"
    assert response.headers["x-aion-conversation-id"] == "thread-1234"
    assert seen["profile"] == "ops"
    assert seen["provider"] == "local-llm"
    assert seen["session_id"] == "thread-1234"
    assert seen["reasoning_effort"] == "off"
    assert "remote_tool" not in seen["user_input"]


def test_completion_stream_is_openai_sse(client):
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "aion_std",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())
    assert ": aion-tool" in raw
    assert '"content": "hel"' in raw
    assert '"content": "lo"' in raw
    assert '"finish_reason": "stop"' in raw
    assert raw.strip().endswith("data: [DONE]")
    # The final event repeats "hello"; only the token deltas are content.
    assert raw.count('"content": "hello"') == 0


def test_n_greater_than_one_is_rejected(client):
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "aion_std",
            "n": 2,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "n_not_supported"


def test_missing_user_message(client):
    response = client.post(
        "/v1/chat/completions",
        json={"model": "aion_std", "messages": [{"role": "system", "content": "x"}]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_user_message"


def test_body_ignores_unknown_openai_fields():
    body = ChatCompletionBody.model_validate(
        {
            "model": "aion_std",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.2,
            "max_tokens": 20,
        }
    )
    assert body.model == "aion_std"
    assert body.stream is False
