"""data_root() fallback when .env still has Docker paths on the host."""

from __future__ import annotations

import os
from pathlib import Path

from src.session_workspace import _REPO_ROOT, data_root


def test_data_root_falls_back_from_app_data_on_host(monkeypatch):
    monkeypatch.setenv("AION_DATA_DIR", "/app/data")
    monkeypatch.setattr("src.session_workspace._running_in_docker", lambda: False)
    root = data_root()
    assert root == (_REPO_ROOT / "data").resolve()


def test_data_root_relative_still_works(monkeypatch, tmp_path):
    monkeypatch.setenv("AION_DATA_DIR", "data")
    root = data_root()
    assert root.name == "data"
    assert "AION_Agent" in str(root) or root.is_absolute()
