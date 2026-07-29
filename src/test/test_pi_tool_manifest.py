from src.runtime.pi_runtime.tool_manifest import (
    relax_pi_tool_parameters,
    tools_to_pi_manifest,
    write_tool_manifest,
)


class _Tool:
    def __init__(self, name: str, function=None):
        self.name = name
        self.description = name
        self.parameters = {"type": "object", "properties": {}}
        self.function = function


def test_tools_to_pi_manifest_filters_blocked():
    manifest = tools_to_pi_manifest(
        "sess-1",
        [_Tool("web_search"), _Tool("draft_execution_plan")],
    )
    names = {row["name"] for row in manifest}
    assert "web_search" in names
    assert "draft_execution_plan" not in names


def test_tools_to_pi_manifest_handles_callable_without_name():
    class DelegationTool:
        server_name = "aion_subagents"

    manifest = tools_to_pi_manifest(
        "sess-2", [_Tool("delegate_to_subagent", DelegationTool())]
    )
    assert manifest == []


def test_tools_to_pi_manifest_records_mcp_server_name():
    class _Fn:
        server_name = "session_sandbox"

    manifest = tools_to_pi_manifest(
        "sess-mcp",
        [_Tool("sandbox_run_python_file", _Fn())],
    )
    assert manifest[0]["source"] == "mcp"
    assert manifest[0]["server_name"] == "session_sandbox"


def test_relax_pi_tool_parameters_drops_required_for_sandbox_write():
    raw = {
        "type": "object",
        "properties": {
            "relative_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["relative_path", "content"],
    }
    relaxed = relax_pi_tool_parameters("sandbox_write_workspace_file", raw)
    assert "required" not in relaxed
    assert relaxed.get("additionalProperties") is True


def test_tools_to_pi_manifest_relaxes_sandbox_write_schema():
    params = {
        "type": "object",
        "properties": {
            "relative_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["relative_path", "content"],
    }
    tool = _Tool("sandbox_write_workspace_file")
    tool.parameters = params
    manifest = tools_to_pi_manifest("sess-relax", [tool])
    assert manifest[0]["parameters"].get("required") is None
    assert manifest[0]["parameters"].get("additionalProperties") is True


def test_write_tool_manifest(tmp_path, monkeypatch):
    sid = "test-session-manifest"
    monkeypatch.setattr(
        "src.runtime.long_run_mode.pi_session_dir",
        lambda _s: str(tmp_path / ".pi"),
    )
    manifest = [
        {
            "name": "web_search",
            "description": "Search",
            "parameters": {"type": "object", "properties": {}},
            "source": "mcp",
            "server_name": "web",
        }
    ]
    path = write_tool_manifest(sid, manifest)
    assert path.is_file()
    assert "web_search" in path.read_text(encoding="utf-8")
