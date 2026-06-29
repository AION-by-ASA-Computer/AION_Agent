"""MCP registry JSON/YAML normalization."""

from __future__ import annotations

import json

from src.mcp_registry_io import flatten_registry_document, load_registry_file


def test_flatten_mcp_servers_json() -> None:
    data = {
        "mcpServers": {
            "toolbox-mysql": {
                "command": "npx",
                "args": ["-y", "server"],
            }
        }
    }
    flat = flatten_registry_document(data)
    assert "toolbox-mysql" in flat
    assert flat["toolbox-mysql"]["command"] == "npx"


def test_flatten_flat_yaml_style() -> None:
    data = {"prometheus": {"command": "python", "args": ["x.py"]}}
    flat = flatten_registry_document(data)
    assert flat["prometheus"]["command"] == "python"


def test_load_registry_json_file(tmp_path) -> None:
    p = tmp_path / "mcp_registry.local.json"
    p.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "remote": {"type": "sse", "url": "https://example.com/sse"}
                }
            }
        ),
        encoding="utf-8",
    )
    flat = load_registry_file(str(p))
    assert flat["remote"]["type"] == "sse"
