"""Regression: console script names must not resolve to clone directories."""

from __future__ import annotations

import os
from pathlib import Path

from src.mcp_manager import MCPManager


def test_resolve_stdio_args_keeps_script_name_when_clone_dir_exists(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    clone = root / "mcp_servers" / "mcp-email-server"
    clone.mkdir(parents=True)
    (clone / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        "src.mcp_manager._repo_root",
        lambda: root,
    )
    args = [
        "run",
        "--directory",
        "mcp_servers/mcp-email-server",
        "mcp-email-server",
        "stdio",
    ]
    resolved = MCPManager.resolve_stdio_args(args)
    assert resolved[0] == "run"
    assert resolved[1] == "--directory"
    assert Path(resolved[2]) == clone.resolve()
    assert resolved[3] == "mcp-email-server"
    assert resolved[4] == "stdio"


def test_resolve_stdio_args_resolves_file_under_mcp_servers(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    mcp = root / "mcp_servers"
    mcp.mkdir(parents=True)
    script = mcp / "server.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr("src.mcp_manager._repo_root", lambda: root)
    resolved = MCPManager.resolve_stdio_args(["server.py"])
    assert resolved[0] == str(script.resolve())
