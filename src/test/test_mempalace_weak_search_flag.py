"""Weak mempalace_search result annotation."""
from __future__ import annotations

import json

from src.runtime.mempalace_tool_scope import enrich_mempalace_tool_result


def test_weak_search_flags_no_relevant_memory() -> None:
    raw = json.dumps(
        {
            "results": [
                {"text": "unrelated PC path", "similarity": 0.25, "room": "join_paths"}
            ]
        }
    )
    out = json.loads(enrich_mempalace_tool_result("mempalace_search", raw))
    assert out["no_relevant_memory"] is True
    assert "explore" in out["suggested_action"].lower()


def test_strong_search_unchanged() -> None:
    raw = json.dumps(
        {
            "results": [
                {"text": "Users to DeviceMovement", "similarity": 0.85, "room": "join_paths"}
            ]
        }
    )
    out = json.loads(enrich_mempalace_tool_result("mempalace_search", raw))
    assert "no_relevant_memory" not in out


def test_other_tools_unchanged() -> None:
    assert enrich_mempalace_tool_result("mempalace_add_drawer", '{"ok":true}') == '{"ok":true}'
