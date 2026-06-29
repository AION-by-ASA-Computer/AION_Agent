"""Session sandbox content roots (uploads, workspace, derived, unpacked)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.session_workspace import SESSION_CONTENT_ROOTS, safe_resolve, session_root


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_safe_resolve_unpacked_and_workspace_paths(isolated_data):
    sid = "test-content-roots"
    root = session_root(sid)
    (root / "unpacked" / "word").mkdir(parents=True)
    (root / "unpacked" / "word" / "document.xml").write_text(
        "<w:document/>", encoding="utf-8"
    )
    (root / "workspace" / "unpacked" / "word").mkdir(parents=True)
    (root / "workspace" / "unpacked" / "word" / "document.xml").write_text(
        "<w:document/>", encoding="utf-8"
    )

    assert safe_resolve(sid, "unpacked/word/document.xml").is_file()
    assert safe_resolve(sid, "workspace/unpacked/word/document.xml").is_file()


def test_session_content_roots_includes_unpacked():
    assert "unpacked" in SESSION_CONTENT_ROOTS
    assert "workspace" in SESSION_CONTENT_ROOTS
