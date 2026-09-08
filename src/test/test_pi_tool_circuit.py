import json

from src.runtime.tool_circuit import (
    maybe_block_repeat_preflight,
    record_preflight_failure,
    reset_session_circuit,
)


def test_circuit_breaker_blocks_after_repeated_failures(monkeypatch):
    monkeypatch.setenv("AION_TOOL_CIRCUIT_BREAKER_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_CIRCUIT_BREAKER_MAX", "2")
    from src.settings import get_settings

    get_settings.cache_clear()
    sid = "sess-cb"
    tool = "sandbox_write_workspace_file"
    args = {"relative_path": "workspace/out.csv"}
    err = json.dumps({"ok": False, "error": "tool_args_truncated"})

    reset_session_circuit(sid)
    assert maybe_block_repeat_preflight(sid, tool, args) is None
    record_preflight_failure(sid, tool, args, err)
    assert maybe_block_repeat_preflight(sid, tool, args) is None
    record_preflight_failure(sid, tool, args, err)
    blocked = maybe_block_repeat_preflight(sid, tool, args)
    assert blocked is not None
    data = json.loads(blocked)
    assert data["error"] == "circuit_breaker"
