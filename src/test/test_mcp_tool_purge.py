"""MCP wrapper purge must be scoped per session."""
import src.main as main_mod
from src.main import _purge_aion_mcp_tool_functions, _register_mcp_tool_function


def test_purge_only_removes_current_session_wrappers():
    fn_a = _register_mcp_tool_function("srv", "tool_a", "session-a")
    fn_b = _register_mcp_tool_function("srv", "tool_b", "session-b")
    fname_a = fn_a.__name__
    fname_b = fn_b.__name__
    assert fname_a in main_mod.__dict__
    assert fname_b in main_mod.__dict__

    _purge_aion_mcp_tool_functions("session-a")
    assert fname_a not in main_mod.__dict__
    assert fname_b in main_mod.__dict__

    _purge_aion_mcp_tool_functions("session-b")
    assert fname_b not in main_mod.__dict__
