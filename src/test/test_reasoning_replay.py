"""Replay del reasoning (interleaved thinking) nel loop tool dell'agente."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from haystack.dataclasses import ChatMessage, ReasoningContent, StreamingChunk, ToolCall
from haystack.utils.auth import Secret

import src.runtime.llm_lite_llm_adapter as adapter  # noqa: F401  (applica le patch)
from src.haystack_chat import chat_message_reasoning_text
from src.runtime.llm_call_audit import serialize_messages
from src.runtime.reasoning_effort import merge_generation_kwargs

import haystack_integrations.components.generators.litellm.chat.chat_generator as litellm_chat_mod


def _wrapper(model: str = "vllm/AIONQ35-35-Q8B") -> adapter.LiteLLMChatGeneratorWrapper:
    return adapter.LiteLLMChatGeneratorWrapper(
        model=model,
        api_base_url="http://localhost:9999/v1",
        api_key=Secret.from_token("test-key"),
        timeout=60.0,
    )


def _assistant_with_reasoning() -> ChatMessage:
    return ChatMessage.from_assistant(
        tool_calls=[
            ToolCall(tool_name="ssh_exec", arguments={"cmd": "uptime"}, id="c1")
        ],
        reasoning=ReasoningContent(reasoning_text="Controllo prima il load average."),
    )


def _wire_messages(wrapper, messages):
    kwargs = wrapper.generator._build_litellm_kwargs(messages, None, None, None)
    return kwargs["messages"]


def test_non_streaming_build_chat_message_keeps_reasoning():
    choice = SimpleNamespace(
        index=0,
        finish_reason="tool_calls",
        message=SimpleNamespace(
            content=None,
            reasoning_content="Serve il disco.",
            tool_calls=[
                SimpleNamespace(
                    id="c1",
                    function=SimpleNamespace(name="df", arguments='{"path": "/"}'),
                )
            ],
        ),
    )
    response = SimpleNamespace(model="m", usage=None)
    msg = litellm_chat_mod._build_chat_message(response, choice)
    assert msg.reasoning is not None
    assert msg.reasoning.reasoning_text == "Serve il disco."
    assert msg.tool_calls[0].tool_name == "df"


def test_streaming_aggregation_collects_meta_reasoning():
    chunks = [
        StreamingChunk(content="", meta={"reasoning": "Prima ", "model": "m"}),
        StreamingChunk(content="", meta={"reasoning": "uptime."}),
        StreamingChunk(content="Ok", meta={"finish_reason": "stop"}),
    ]
    msg = litellm_chat_mod._convert_streaming_chunks_to_chat_message(chunks=chunks)
    assert msg.text == "Ok"
    assert msg.reasoning.reasoning_text == "Prima uptime."


def test_reasoning_only_reply_is_left_untouched():
    chunks = [StreamingChunk(content="", meta={"reasoning": "solo pensiero"})]
    msg = litellm_chat_mod._convert_streaming_chunks_to_chat_message(chunks=chunks)
    assert msg.reasoning is None


def test_wire_carries_reasoning_fields(monkeypatch):
    monkeypatch.delenv("AION_REASONING_REPLAY", raising=False)
    monkeypatch.delenv("AION_REASONING_REPLAY_FIELDS", raising=False)
    wire = _wire_messages(
        _wrapper(),
        [ChatMessage.from_user("check-up"), _assistant_with_reasoning()],
    )
    assert "reasoning_content" not in wire[0]
    assert wire[1]["reasoning_content"] == "Controllo prima il load average."
    assert wire[1]["reasoning"] == "Controllo prima il load average."
    assert wire[1]["tool_calls"]


def test_stm_messages_have_no_reasoning_fields(monkeypatch):
    monkeypatch.delenv("AION_REASONING_REPLAY", raising=False)
    wire = _wire_messages(
        _wrapper(), [ChatMessage.from_assistant("risposta precedente")]
    )
    assert "reasoning_content" not in wire[0]
    assert "reasoning" not in wire[0]


def test_replay_disabled(monkeypatch):
    monkeypatch.setenv("AION_REASONING_REPLAY", "0")
    wire = _wire_messages(_wrapper(), [_assistant_with_reasoning()])
    assert "reasoning_content" not in wire[0]
    assert "reasoning" not in wire[0]


def test_replay_custom_fields(monkeypatch):
    monkeypatch.setenv("AION_REASONING_REPLAY_FIELDS", "reasoning")
    wire = _wire_messages(_wrapper(), [_assistant_with_reasoning()])
    assert wire[0]["reasoning"]
    assert "reasoning_content" not in wire[0]


def test_replay_skipped_for_anthropic(monkeypatch):
    monkeypatch.delenv("AION_REASONING_REPLAY", raising=False)
    wire = _wire_messages(
        _wrapper("anthropic/claude-sonnet-4-20250514"), [_assistant_with_reasoning()]
    )
    assert "reasoning_content" not in wire[0]


def test_clear_thinking_flag():
    on = merge_generation_kwargs({}, "medium", model="Qwen/Qwen3.8-Flash-Next")
    ctk = on["extra_body"]["chat_template_kwargs"]
    assert ctk["clear_thinking"] is False
    off = merge_generation_kwargs({}, "off", model="Qwen/Qwen3.8-Flash-Next")
    assert "clear_thinking" not in off["extra_body"]["chat_template_kwargs"]


def test_budget_and_audit_see_reasoning():
    msg = _assistant_with_reasoning()
    assert chat_message_reasoning_text(msg) == "Controllo prima il load average."
    assert chat_message_reasoning_text(ChatMessage.from_user("x")) == ""
    rows = serialize_messages([msg])
    assert rows[0]["reasoning"] == "Controllo prima il load average."


def test_agent_loop_replays_reasoning_on_second_call(monkeypatch):
    """Due step reali dell'Agent Haystack con litellm.acompletion intercettato."""
    from haystack.components.agents import Agent
    from haystack.tools import Tool

    monkeypatch.delenv("AION_REASONING_REPLAY", raising=False)
    monkeypatch.delenv("AION_REASONING_REPLAY_FIELDS", raising=False)
    calls: list[dict] = []

    def _response(message, finish):
        return SimpleNamespace(
            model="m",
            usage=None,
            choices=[SimpleNamespace(index=0, finish_reason=finish, message=message)],
        )

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _response(
                SimpleNamespace(
                    content=None,
                    reasoning_content="Guardo l'uptime.",
                    tool_calls=[
                        SimpleNamespace(
                            id="c1",
                            function=SimpleNamespace(name="uptime", arguments="{}"),
                        )
                    ],
                ),
                "tool_calls",
            )
        return _response(
            SimpleNamespace(
                content="Host ok.", reasoning_content="Fatto.", tool_calls=None
            ),
            "stop",
        )

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    tool = Tool(
        name="uptime",
        description="uptime",
        parameters={"type": "object", "properties": {}},
        function=lambda: "up 3 days, load 0.10",
    )
    agent = Agent(chat_generator=_wrapper(), tools=[tool])
    agent.warm_up()
    result = asyncio.run(agent.run_async(messages=[ChatMessage.from_user("check-up")]))

    assert len(calls) == 2
    second = calls[1]["messages"]
    assistant = [m for m in second if m.get("role") == "assistant"]
    assert assistant and assistant[0]["tool_calls"]
    assert assistant[0]["reasoning_content"] == "Guardo l'uptime."
    assert assistant[0]["reasoning"] == "Guardo l'uptime."
    assert result["last_message"].text == "Host ok."
