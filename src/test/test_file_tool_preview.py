"""Early SSE preview for filesystem write tools."""

from src.runtime.file_tool_preview import build_file_tool_preview_events, is_file_preview_tool


def test_is_file_preview_tool():
    assert is_file_preview_tool("sandbox_write_workspace_file")
    assert is_file_preview_tool("session_sandbox-sandbox_write_workspace_file")
    assert not is_file_preview_tool("sandbox_read_text_file")


def test_write_preview_emits_start_and_chunks():
    content = "x" * 12000
    events, meta = build_file_tool_preview_events(
        "sandbox_write_workspace_file",
        {"relative_path": "workspace/create_doc.js", "content": content},
    )
    assert meta["preview_emitted"] is True
    assert events[0]["type"] == "artifact_start"
    assert events[0]["artifact"]["pending"] is True
    assert events[0]["artifact"]["type"] == "javascript"
    content_events = [e for e in events if e["type"] == "artifact_content"]
    assert len(content_events) >= 2
