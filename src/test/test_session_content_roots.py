"""Session sandbox content roots (uploads, workspace, derived, unpacked)."""

from __future__ import annotations


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


def test_session_root_rejects_traversal(isolated_data):
    with pytest.raises(ValueError):
        session_root("../../etc/passwd")

    with pytest.raises(ValueError):
        session_root("..\\..\\windows")

    with pytest.raises(ValueError):
        session_root("/absolute/path")


def test_safe_resolve_rejects_traversal(isolated_data):
    sid = "test-traversal-sid"
    with pytest.raises(ValueError):
        safe_resolve(sid, "../outside.txt")

    with pytest.raises(ValueError):
        safe_resolve(sid, "uploads/../../secret.txt")


def test_session_venv_python_allows_interpreter_symlink(isolated_data):
    """The venv python symlink targets the system interpreter and must stay usable."""
    import os

    from src.tools.session_venv import session_venv_exists, session_venv_python

    sid = "test-venv-symlink"
    root = session_root(sid)
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    outside = isolated_data / "system-python"
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    py313 = bin_dir / "python3.13"
    py313.symlink_to(outside)
    (bin_dir / "python").symlink_to("python3.13")

    resolved = session_venv_python(sid)
    assert resolved == bin_dir / "python"
    assert os.path.isfile(resolved)
    assert session_venv_exists(sid)


def test_session_fs_confines_relative_paths(isolated_data):
    from src.session_workspace import session_fs

    sid = "test-fs-confine"
    root = session_root(sid)
    uploads = session_fs(sid, "uploads")
    assert uploads == str((root / "uploads").resolve())
    assert session_fs(sid).startswith(str(root))

    with pytest.raises(ValueError):
        session_fs(sid, "../secret")
