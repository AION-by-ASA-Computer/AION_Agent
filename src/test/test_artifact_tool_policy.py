"""Tests for artifact-tool filtering policy."""

from src.runtime.artifact_tool_policy import (
    STREAM_ARTIFACT_BLOCKED_TOOLS,
    stream_artifact_tools_blocked,
)


def test_stream_artifact_does_not_block_write_by_default(monkeypatch):
    monkeypatch.delenv("AION_ARTIFACT_STREAM_LEGACY", raising=False)
    assert stream_artifact_tools_blocked() == STREAM_ARTIFACT_BLOCKED_TOOLS
    assert "sandbox_write_workspace_file" not in stream_artifact_tools_blocked()


def test_legacy_stream_blocks_write(monkeypatch):
    monkeypatch.setenv("AION_ARTIFACT_STREAM_LEGACY", "1")
    from importlib import reload
    import src.runtime.artifact_tool_policy as pol

    reload(pol)
    assert "sandbox_write_workspace_file" in pol.stream_artifact_tools_blocked()
