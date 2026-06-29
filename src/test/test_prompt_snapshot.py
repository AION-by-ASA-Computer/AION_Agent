"""Tests for full prompt snapshot serialization."""

from haystack.dataclasses import ChatMessage

from src.runtime.prompt_snapshot import (
    build_prompt_snapshot,
    patch_prompt_snapshot_output,
    store_prompt_snapshot,
    track_prepend_layer,
)


class _FakeTool:
    def __init__(self, name: str, description: str, spec: dict | None = None):
        self.name = name
        self.description = description
        self.tool_spec = spec


class _FakeAgent:
    def __init__(self, system_prompt: str, tools: list | None = None):
        self.system_prompt = system_prompt
        self.tools = tools or []


def test_track_prepend_layer_detects_prefix():
    layers: list[dict[str, str]] = []
    track_prepend_layer(layers, "sql_query_memory", "hello", "[SQL]\n\nhello")
    assert len(layers) == 1
    assert layers[0]["key"] == "sql_query_memory"
    assert layers[0]["text"] == "[SQL]\n\n"


def test_build_prompt_snapshot_includes_system_and_messages():
    agent = _FakeAgent(
        "You are helpful.",
        tools=[_FakeTool("query", "Run SQL", {"type": "object"})],
    )
    messages = [
        ChatMessage.from_user("first turn"),
        ChatMessage.from_assistant("ok"),
        ChatMessage.from_user("second turn"),
    ]
    snapshot = build_prompt_snapshot(
        agent,
        messages,
        inject_layers=[{"key": "user_input", "text": "second turn"}],
        turn_meta={"agent_mode": "normal"},
        generation_kwargs={"temperature": 0.2},
    )
    assert snapshot["system_prompt"] == "You are helpful."
    assert len(snapshot["messages"]) == 3
    assert snapshot["messages"][-1]["content"] == "second turn"
    assert snapshot["tools"][0]["name"] == "query"
    assert "=== SYSTEM ===" in snapshot["raw_concatenated"]
    assert "=== USER [2] ===" in snapshot["raw_concatenated"]
    assert snapshot["stats"]["total"] > 0


def test_patch_prompt_snapshot_output_appends_assistant_text():
    snapshot = build_prompt_snapshot(_FakeAgent("sys"), [ChatMessage.from_user("hi")])
    store_prompt_snapshot("sess-1", snapshot, assistant_message_id="asst-1")
    patched = patch_prompt_snapshot_output(
        "sess-1",
        "asst-1",
        assistant_output='plan title="Test"\n## Goal\nG',
        plan_coerced_markdown="<plan>\n## Goal\nG\n</plan>",
        plan_intercepts=1,
    )
    assert patched is not None
    assert patched["assistant_output"].startswith("plan title=")
    assert "=== ASSISTANT OUTPUT ===" in patched["raw_concatenated"]
    assert patched["phase"] == "complete"
    assert patched["plan_intercepts"] == 1
    assert patched["turn_metrics"]["artifact_parse_hits"] == 0
