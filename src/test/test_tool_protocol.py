"""Tool protocol helpers."""

import os

from src.runtime.tool_protocol import (
    format_tool_error,
    should_skip_tools_for_truncation,
)


def test_should_skip_tools_when_flag_and_length(monkeypatch):
    monkeypatch.setenv("AION_HARNESS_V2_TOOLS", "1")
    assert should_skip_tools_for_truncation("length") is True
    assert should_skip_tools_for_truncation("stop") is False


def test_format_tool_error_includes_name():
    err = format_tool_error("my_tool", ValueError("boom"))
    assert "my_tool" in err
    assert "boom" in err.lower() or "ValueError" in err
