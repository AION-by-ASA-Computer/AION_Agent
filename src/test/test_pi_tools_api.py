"""Regression tests for Pi internal tool invoke API."""

from src.runtime.turn_compaction import truncate_tool_result


def test_pi_tools_truncate_passes_result_not_tool_name():
    payload = '{"results":[{"title":"A","url":"https://example.com"}]}'
    out = truncate_tool_result(payload, tool_name="web_search")
    assert out == payload
    assert out != "web_search"
