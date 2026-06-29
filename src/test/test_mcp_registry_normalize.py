"""Entrypoint detection for installed MCP servers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.mcp_registry_normalize import detect_stdio_entrypoint


@pytest.fixture
def fake_py_mcp(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    clone = root / "mcp_servers" / "fake-email"
    clone.mkdir(parents=True)
    (clone / "pyproject.toml").write_text(
        """
[project]
name = "fake-email"
version = "0.0.1"
[project.scripts]
fake-email = "fake_email.cli:app"
""".strip(),
        encoding="utf-8",
    )
    registry = {
        "fake-email": {
            "aion_market_install": "git",
            "aion_market_clone_path": "mcp_servers/fake-email",
        }
    }

    class FakeMcpManager:
        _registry = registry

        def get_server_config(self, slug: str):
            return dict(registry.get(slug) or {})

    import src.mcp_registry_normalize as norm

    monkeypatch.setattr(norm, "mcp_manager", FakeMcpManager())
    monkeypatch.setattr(norm, "_repo_root", lambda: root)
    return "fake-email"


def test_detect_stdio_pyproject_uv(fake_py_mcp, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: cmd == "uv")
    cmd, args = detect_stdio_entrypoint(fake_py_mcp)
    assert cmd == "uv"
    assert args[:3] == ["run", "--directory", "mcp_servers/fake-email"]
    assert args[-1] == "stdio"


def test_detect_stdio_node_package_json(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    clone = root / "mcp_servers" / "fake-node"
    clone.mkdir(parents=True)
    (clone / "package.json").write_text(
        json.dumps({"name": "fake-node", "main": "build/index.js"}),
        encoding="utf-8",
    )
    (clone / "build").mkdir()
    (clone / "build" / "index.js").write_text("module.exports = {};", encoding="utf-8")

    registry = {
        "fake-node": {
            "aion_market_clone_path": "mcp_servers/fake-node",
        }
    }

    class FakeMcpManager:
        _registry = registry

        def get_server_config(self, slug: str):
            return dict(registry.get(slug) or {})

    import src.mcp_registry_normalize as norm

    monkeypatch.setattr(norm, "mcp_manager", FakeMcpManager())
    monkeypatch.setattr(norm, "_repo_root", lambda: root)
    cmd, args = detect_stdio_entrypoint("fake-node")
    assert cmd == "node"
    assert args[0].endswith("build/index.js")


def test_detect_stdio_node_bin_over_main(tmp_path, monkeypatch):
    """Il campo 'bin' ha priorità su 'main' e su file fisici (es. playwright-mcp)."""
    root = tmp_path / "repo"
    clone = root / "mcp_servers" / "fake-bin"
    clone.mkdir(parents=True)
    (clone / "package.json").write_text(
        json.dumps(
            {
                "name": "fake-bin",
                "main": "index.js",
                "bin": {"fake-bin": "cli.js"},
            }
        ),
        encoding="utf-8",
    )
    # index.js esiste fisicamente (modulo export, NON il CLI)
    (clone / "index.js").write_text("module.exports = {};", encoding="utf-8")
    # cli.js è il vero entrypoint CLI
    (clone / "cli.js").write_text("#!/usr/bin/env node", encoding="utf-8")

    registry = {
        "fake-bin": {
            "aion_market_clone_path": "mcp_servers/fake-bin",
        }
    }

    class FakeMcpManager:
        _registry = registry

        def get_server_config(self, slug: str):
            return dict(registry.get(slug) or {})

    import src.mcp_registry_normalize as norm

    monkeypatch.setattr(norm, "mcp_manager", FakeMcpManager())
    monkeypatch.setattr(norm, "_repo_root", lambda: root)
    cmd, args = detect_stdio_entrypoint("fake-bin")
    assert cmd == "node"
    assert args[0].endswith("cli.js")


def test_detect_stdio_node_bin_only(tmp_path, monkeypatch):
    """Se c'è solo 'bin' (senza 'main'), viene usato quello (es. playwright-mcp originale)."""
    root = tmp_path / "repo"
    clone = root / "mcp_servers" / "fake-bin-only"
    clone.mkdir(parents=True)
    (clone / "package.json").write_text(
        json.dumps(
            {
                "name": "fake-bin-only",
                "bin": {"fake-bin-only": "cli.js"},
            }
        ),
        encoding="utf-8",
    )
    # index.js esiste fisicamente (modulo export)
    (clone / "index.js").write_text("module.exports = {};", encoding="utf-8")
    # cli.js è il vero entrypoint CLI
    (clone / "cli.js").write_text("#!/usr/bin/env node", encoding="utf-8")

    registry = {
        "fake-bin-only": {
            "aion_market_clone_path": "mcp_servers/fake-bin-only",
        }
    }

    class FakeMcpManager:
        _registry = registry

        def get_server_config(self, slug: str):
            return dict(registry.get(slug) or {})

    import src.mcp_registry_normalize as norm

    monkeypatch.setattr(norm, "mcp_manager", FakeMcpManager())
    monkeypatch.setattr(norm, "_repo_root", lambda: root)
    cmd, args = detect_stdio_entrypoint("fake-bin-only")
    assert cmd == "node"
    assert args[0].endswith("cli.js")


def test_detect_stdio_node_bin_file_missing_fallback(tmp_path, monkeypatch):
    """Se 'bin' punta a un file inesistente, la cascata continua (fallback)."""
    root = tmp_path / "repo"
    clone = root / "mcp_servers" / "fake-bin-missing"
    clone.mkdir(parents=True)
    (clone / "package.json").write_text(
        json.dumps(
            {
                "name": "fake-bin-missing",
                "bin": {"fake-bin-missing": "nonexistent.js"},
                "main": "index.js",
            }
        ),
        encoding="utf-8",
    )
    # index.js esiste fisicamente
    (clone / "index.js").write_text("module.exports = {};", encoding="utf-8")
    # nonexistent.js non esiste

    registry = {
        "fake-bin-missing": {
            "aion_market_clone_path": "mcp_servers/fake-bin-missing",
        }
    }

    class FakeMcpManager:
        _registry = registry

        def get_server_config(self, slug: str):
            return dict(registry.get(slug) or {})

    import src.mcp_registry_normalize as norm

    monkeypatch.setattr(norm, "mcp_manager", FakeMcpManager())
    monkeypatch.setattr(norm, "_repo_root", lambda: root)
    cmd, args = detect_stdio_entrypoint("fake-bin-missing")
    # Dovrebbe fallback a index.js (main field o fisico)
    assert cmd == "node"
    assert args[0].endswith("index.js")
