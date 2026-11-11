"""One active profile per chat session in the agent cache.

Building (or reusing) the agent of profile X for a session must drop cached
agents of other profiles for that same session, while leaving other sessions
alone, so tools, MCP servers and skills never mix between profiles.
"""

from __future__ import annotations

import src.main as main_mod


def _key(session: str, profile: str) -> str:
    """Cache key shaped like get_agent's: session, profile, then the rest."""
    return f"{session}\0{profile}\0sig\0user\0tenant"


def test_evicts_only_other_profiles_of_same_session(monkeypatch):
    """aion_std of session s1 goes, generic_assistant of s1 and s2 entries stay."""
    cache = main_mod.OrderedDict(
        [
            (_key("s1", "aion_std"), ("agent-a", "aion_std")),
            (_key("s1", "generic_assistant"), ("agent-g", "generic_assistant")),
            (_key("s2", "aion_std"), ("agent-b", "aion_std")),
        ]
    )
    monkeypatch.setattr(main_mod, "_AGENT_CACHE", cache)

    evicted = main_mod._evict_other_profile_agents_locked("s1", "generic_assistant")

    assert evicted == 1
    assert list(cache) == [_key("s1", "generic_assistant"), _key("s2", "aion_std")]


def test_session_prefix_does_not_match_longer_session_ids(monkeypatch):
    """Session "s1" must not evict entries of session "s10"."""
    cache = main_mod.OrderedDict([(_key("s10", "aion_std"), ("agent", "aion_std"))])
    monkeypatch.setattr(main_mod, "_AGENT_CACHE", cache)

    assert main_mod._evict_other_profile_agents_locked("s1", "generic_assistant") == 0
    assert len(cache) == 1


def test_profile_switch_drops_deferred_pool_of_previous_profile(monkeypatch):
    """Switching profile also forgets the tools the previous profile deferred."""
    from src.runtime.tool_exposure import (
        clear_deferred_tools,
        deferred_tools_for,
        remember_deferred_tools,
    )

    class _T:
        def __init__(self, name):
            self.name = name

    sid = "switch-pool"
    cache = main_mod.OrderedDict([(_key(sid, "aion_std"), ("agent", "aion_std"))])
    monkeypatch.setattr(main_mod, "_AGENT_CACHE", cache)
    remember_deferred_tools(sid, [_T("web_search")], "aion_std")
    remember_deferred_tools(sid, [_T("ocr_file")], "generic_assistant")
    try:
        main_mod._evict_other_profile_agents_locked(sid, "generic_assistant")
        assert deferred_tools_for(sid, "aion_std") == []
        assert [t.name for t in deferred_tools_for(sid, "generic_assistant")] == [
            "ocr_file"
        ]
    finally:
        clear_deferred_tools(sid)
