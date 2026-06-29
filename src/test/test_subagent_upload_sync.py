"""Copia uploads parent→child per sub-agent (MVP)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.session_workspace import ensure_session_dirs, sync_parent_uploads_to_child


@pytest.fixture()
def data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("AION_DATA_DIR", td)
        yield Path(td)


def test_sync_copies_uploads(data_dir):
    parent = "thread-parent-1234"
    child = "sub_planner_abcdef01"
    ensure_session_dirs(parent)
    ensure_session_dirs(child)
    p_root = data_dir / "sessions" / parent / "uploads"
    p_root.mkdir(parents=True, exist_ok=True)
    (p_root / "hello.txt").write_text("world", encoding="utf-8")

    meta = sync_parent_uploads_to_child(parent, child)
    assert meta["ok"] is True
    assert "uploads/hello.txt" in meta["copied"]
    dst = data_dir / "sessions" / child / "uploads" / "hello.txt"
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == "world"


def test_sync_invalid_session_skips(data_dir):
    meta = sync_parent_uploads_to_child("../evil", "sub_x_0123456789")
    assert meta["ok"] is False
    assert meta["errors"]
