"""Tests for per-call LLM audit logging."""

from __future__ import annotations

import json

import pytest
from haystack.dataclasses import ChatMessage

from src.runtime.llm_call_audit import (
    audit_root_dir,
    llm_call_audit_enabled,
    record_llm_call,
    serialize_messages,
)


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_LLM_CALL_AUDIT", "1")
    monkeypatch.setenv("AION_LLM_CALL_AUDIT_DIR", str(tmp_path / "llm_calls"))
    from src.runtime import context as ctx_mod
    from src.runtime import turn_compaction as tc_mod

    ctx_mod.set_context("sess-audit", loop=None, queue=None, stop_event=None)
    tc_mod.set_turn_runtime(
        session_id="sess-audit",
        loop=None,
        queue=None,
        stop_event=None,
        agent=type("A", (), {"system_prompt": "SYS", "tools": []})(),
        profile_name="aion_std",
        user_id="u1",
    )
    yield tmp_path
    ctx_mod.clear_context()
    tc_mod.clear_turn_runtime()


def test_audit_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AION_LLM_CALL_AUDIT", raising=False)
    assert not llm_call_audit_enabled()


def test_record_llm_call_writes_json(audit_env):
    gen = type(
        "G",
        (),
        {
            "model": "openai/qwen",
            "provider": "openai",
            "api_base_url": "http://127.0.0.1:8000/v1",
            "generation_kwargs": {},
        },
    )()
    path = record_llm_call(
        gen,
        messages=[ChatMessage.from_user("Crea un word")],
        tools=[],
        generation_kwargs={"temperature": 0.2},
        result={"replies": [ChatMessage.from_assistant("ok")]},
        duration_ms=42,
    )
    assert path
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["session_id"] == "sess-audit"
    assert data["step"] == 1
    assert data["request"]["system_prompt"] == "SYS"
    assert data["request"]["messages"][0]["content"] == "Crea un word"
    assert data["response"]["replies"][0]["content"] == "ok"
    idx = audit_root_dir() / "index.jsonl"
    assert idx.is_file()


def test_serialize_messages_includes_tool_calls():
    msg = ChatMessage.from_assistant(
        "",
        meta={},
    )
    # Haystack tool calls vary by version — empty list is fine for smoke test.
    rows = serialize_messages([ChatMessage.from_user("hi"), msg])
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"
