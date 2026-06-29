"""Smoke tests for trigger_research / manage_research tools."""

import json

from src.runtime.native_tools.research_tools import run_manage_research, run_trigger_research


def test_trigger_research_returns_session_id(monkeypatch):
    started = {}

    class FakeHandler:
        def start_research(self, sid, query, **kwargs):
            started["sid"] = sid
            started["query"] = query
            return {"session_id": sid, "status": "running", "query": query}

    monkeypatch.setattr(
        "src.research.handler.get_research_handler",
        lambda: FakeHandler(),
    )
    monkeypatch.setattr(
        "src.research.handler.deep_research_enabled",
        lambda: True,
    )
    raw = run_trigger_research(json.dumps({"topic": "quantum computing 2026"}), user_id="alice")
    data = json.loads(raw)
    assert data["exit_code"] == 0
    assert data["ui_event"] == "research_started"
    assert data["research_session_id"]
    assert started["query"] == "quantum computing 2026"


def test_manage_research_list_empty(monkeypatch):
    import src.research.handler as rh

    class FakeHandler:
        def list_library(self, owner, **kwargs):
            return []

    monkeypatch.setattr(rh, "get_research_handler", lambda: FakeHandler())
    raw = run_manage_research(json.dumps({"action": "list"}), user_id="bob")
    data = json.loads(raw)
    assert data["exit_code"] == 0
    assert "No research" in data["output"]
