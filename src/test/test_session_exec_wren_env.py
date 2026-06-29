"""Wren CLI env injection for sandbox_exec_allowlisted."""
from __future__ import annotations

import os
from unittest.mock import patch

from src.tools.session_exec import _build_exec_env, _resolve_wren_home, _wren_exec_timeout_sec


def test_wren_exec_default_timeout():
    assert _wren_exec_timeout_sec(30.0) == 180.0
    assert _wren_exec_timeout_sec(60.0) == 60.0


def test_wren_env_injects_project_home(tmp_path, monkeypatch):
    project = tmp_path / "wren_proj"
    project.mkdir()
    (project / ".env").write_text("POSTGRES_HOST=db.example\n")
    monkeypatch.setenv("AION_WREN_PROJECT_PATH", str(project))
    monkeypatch.setenv("HOME", str(tmp_path / "backend_home"))
    env = _build_exec_env("sess-1", ["wren", "--sql", "SELECT 1"])
    assert env["WREN_PROJECT_HOME"] == str(project.resolve())
    assert env["POSTGRES_HOST"] == "db.example"
    assert env["WREN_HOME"] == str((tmp_path / "backend_home" / ".wren").resolve())


def test_wren_home_honors_explicit_override(tmp_path, monkeypatch):
    custom = tmp_path / "shared_wren"
    monkeypatch.setenv("AION_WREN_HOME", str(custom))
    assert _resolve_wren_home() == custom.resolve()


def test_wren_home_ignores_mcp_isolated_home(tmp_path, monkeypatch):
    """MCP subprocesses set HOME to data/users/<uid>/mcp_home — Wren must not use that."""
    isolated = tmp_path / "data" / "users" / "demo" / "mcp_home"
    isolated.mkdir(parents=True)
    real = tmp_path / "real_wren"
    monkeypatch.delenv("AION_WREN_HOME", raising=False)
    monkeypatch.delenv("WREN_HOME", raising=False)
    monkeypatch.setenv("HOME", str(isolated))
    monkeypatch.setattr(
        "src.tools.session_exec._system_user_home",
        lambda: tmp_path / "backend_user",
    )
    (tmp_path / "backend_user" / ".wren").mkdir(parents=True)
    assert _resolve_wren_home() == (tmp_path / "backend_user" / ".wren").resolve()
