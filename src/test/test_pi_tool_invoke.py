import pytest

from src.runtime.context import bind_session_id, get_current_session_id
from src.runtime.pi_runtime.tool_invoke import _ensure_mcp_session_context


@pytest.mark.asyncio
async def test_ensure_mcp_session_context_sets_profile(monkeypatch):
    from src.mcp_manager import mcp_manager

    calls = []

    def _fake_set(sid, ctx):
        calls.append((sid, ctx.profile_slug, ctx.user_id))

    monkeypatch.setattr(mcp_manager, "get_session_context", lambda _s: None)
    monkeypatch.setattr(mcp_manager, "set_session_context", _fake_set)

    await _ensure_mcp_session_context("sess-1", "generic_assistant", "user42")
    assert calls == [("sess-1", "generic_assistant", "user42")]


def test_bind_session_id_sets_context_for_pi_bridge():
    with bind_session_id("pi-sess-99"):
        assert get_current_session_id() == "pi-sess-99"
    assert get_current_session_id() == "default"
