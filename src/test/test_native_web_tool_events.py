"""Tool event bus per esecutori nativi web_search / web_fetch_page."""

from __future__ import annotations

import asyncio
import contextvars
import json
import threading

import pytest

from src.runtime.context import (
    clear_context,
    get_context,
    get_current_session_id,
    set_context,
)
from src.runtime.native_tools.factory_table import WebSearchExecutor
from src.runtime.native_tools.web_providers import run_web_fetch_page
from src.runtime.tool_events import tool_event_bus


def test_web_search_executor_emits_tool_start_end(monkeypatch):
    async def _run():
        session_id = "test-native-web-tool-events"
        loop = asyncio.get_running_loop()
        sub_q = tool_event_bus.subscribe(session_id)
        monkeypatch.setenv("AION_TOOL_RESULT_FORMAT", "json")

        try:
            monkeypatch.setattr(
                "src.runtime.native_tools.factory_table.run_web_search",
                lambda query, max_results=None, language=None: json.dumps(
                    {"query": query, "provider_used": "tavily", "results": []}
                ),
            )

            def run_in_worker():
                set_context(session_id, loop, asyncio.Queue(), asyncio.Event())
                try:
                    return WebSearchExecutor()("municipality noise", max_results=3)
                finally:
                    clear_context()

            worker = asyncio.create_task(asyncio.to_thread(run_in_worker))
            ev1 = await asyncio.wait_for(sub_q.get(), timeout=2.0)
            ev2 = await asyncio.wait_for(sub_q.get(), timeout=2.0)
            out = await worker
        finally:
            tool_event_bus.unsubscribe(session_id, sub_q)

        assert ev1["type"] == "tool_start"
        assert ev1.get("id")
        assert ev1["name"] == "web_search"
        assert ev1["input"]["query"] == "municipality noise"
        assert ev2["type"] == "tool_end"
        assert ev2.get("id") == ev1.get("id")
        assert ev2["name"] == "web_search"
        assert "results" in ev2["output"]
        data = json.loads(out)
        assert data["results"] == []

    asyncio.run(_run())


def test_tool_event_bus_logs_info(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="aion.tool_events")

    session_id = "test-logging-session"
    tool_event_bus.put_event(
        session_id,
        {
            "type": "tool_start",
            "id": "call-1",
            "name": "my_test_tool",
            "input": {"arg": 1},
            "profile": "odoo_assistant",
        },
    )
    tool_event_bus.put_event(
        session_id,
        {
            "type": "tool_end",
            "id": "call-1",
            "name": "my_test_tool",
            "output": "ok",
            "profile": "odoo_assistant",
        },
    )
    tool_event_bus.put_event(
        session_id,
        {
            "type": "tool_error",
            "id": "call-2",
            "name": "my_test_tool",
            "error": "failed",
            "profile": "odoo_assistant",
        },
    )

    logs = [r for r in caplog.records if r.name == "aion.tool_events"]
    assert len(logs) >= 3

    start_log = next(r for r in logs if "Tool execution started" in r.message)
    assert "my_test_tool" in start_log.message
    assert "call-1" in start_log.message
    assert "profile=odoo_assistant" in start_log.message
    assert (
        getattr(start_log, "profile", None) == "odoo_assistant"
        or start_log.__dict__.get("profile_name") == "odoo_assistant"
    )

    end_log = next(r for r in logs if "Tool execution completed" in r.message)
    assert "my_test_tool" in end_log.message
    assert "profile=odoo_assistant" in end_log.message

    error_log = next(r for r in logs if "Tool execution failed" in r.message)
    assert "failed" in error_log.message
    assert "profile=odoo_assistant" in error_log.message


def test_agent_forward_propagates_via_copy_context_like_haystack_tool_invoker():
    """ToolInvoker esegue i tool con snap.run(...); ContextVar deve propagare session_id e loop."""
    loop_obj = object()
    set_context("sess-tool-pool", loop_obj, None, None)
    snap = contextvars.copy_context()
    out: list[object] = []

    def in_worker():
        out.append(get_current_session_id())
        out.append(get_context().get("loop"))

    try:
        t = threading.Thread(target=lambda: snap.run(in_worker))
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert out[0] == "sess-tool-pool"
        assert out[1] is loop_obj
    finally:
        clear_context()


def test_run_web_fetch_page_rejects_pdf_url_by_path(monkeypatch):
    monkeypatch.setenv("AION_TOOL_RESULT_FORMAT", "json")
    raw = run_web_fetch_page("https://example.org/guidelines/document.pdf")
    data = json.loads(raw)
    assert data.get("error") == "pdf_not_text_extractable"
    assert "document.pdf" in data.get("url", "")
