"""Admins must not be able to read users' chats through /admin/* helpers."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.test.test_api_endpoints import _reset_unified_db


def test_private_data_paths_are_detected(tmp_path: Path):
    from src.api.admin import _is_private_data_path, _project_root
    from src.session_workspace import data_root

    assert _is_private_data_path(data_root() / "aion.db")
    assert _is_private_data_path(
        data_root() / "sessions" / "conv-1" / "uploads" / "a.txt"
    )
    assert _is_private_data_path(_project_root() / ".env")
    assert _is_private_data_path(tmp_path / "chat_memory.sqlite3")
    assert not _is_private_data_path(_project_root() / "src" / "api" / "admin.py")


def test_investigable_path_only_project_code(tmp_path: Path):
    from src.api.admin import _investigable_path, _project_root

    root = _project_root().resolve()
    assert _investigable_path("src/api/admin.py") == root / "src" / "api" / "admin.py"
    assert _investigable_path(str(root / "src" / "api" / "admin.py"))
    for bad in (
        "/etc/hosts",
        "/proc/self/environ",
        "../outside.py",
        "src/../../outside.py",
        str(tmp_path / "x.py"),
        ".env",
        ".git/config",
        "config/mcp_registry.local.yaml",
        "data/aion.db",
        "certs/server.key",
    ):
        assert _investigable_path(bad) is None, bad


def test_investigable_path_rejects_symlink_out_of_project(tmp_path: Path):
    from src.api.admin import _investigable_path, _project_root

    outside = tmp_path / "secret.txt"
    outside.write_text("s")
    link = _project_root() / "src" / "test" / "_tmp_link_out.txt"
    try:
        link.symlink_to(outside)
        assert _investigable_path(str(link)) is None
    finally:
        link.unlink(missing_ok=True)


@pytest.mark.anyio
async def test_security_investigate_rejects_files_outside_project(
    monkeypatch, tmp_path: Path
):
    await _reset_unified_db(monkeypatch, tmp_path)

    from src.api.main import app

    with TestClient(app) as client:
        for p in ("/etc/hosts", "/proc/self/environ", "/no/such/file"):
            res = client.get("/admin/security/investigate", params={"path": p})
            assert res.status_code == 403, p
        res = client.get("/admin/security/investigate", params={"path": "src/nope.py"})
        assert res.status_code == 404


@pytest.mark.anyio
async def test_security_investigate_rejects_private_files(monkeypatch, tmp_path: Path):
    await _reset_unified_db(monkeypatch, tmp_path)

    db_file = tmp_path / "copy.db"
    db_file.write_text("conversations")

    from src.api.main import app

    with TestClient(app) as client:
        res = client.get("/admin/security/investigate", params={"path": str(db_file)})
        assert res.status_code == 403
