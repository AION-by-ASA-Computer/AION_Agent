"""Admins must not be able to read users' chats through /admin/* helpers."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.test.test_api_endpoints import _reset_unified_db


def test_private_data_paths_are_detected(tmp_path: Path):
    from src.api.admin import _is_private_data_path, _project_root
    from src.session_workspace import data_root

    assert _is_private_data_path(data_root() / "aion.db")
    assert _is_private_data_path(data_root() / "sessions" / "conv-1" / "uploads" / "a.txt")
    assert _is_private_data_path(_project_root() / ".env")
    assert _is_private_data_path(tmp_path / "chat_memory.sqlite3")
    assert not _is_private_data_path(_project_root() / "src" / "api" / "admin.py")


@pytest.mark.anyio
async def test_security_investigate_rejects_private_files(monkeypatch, tmp_path: Path):
    await _reset_unified_db(monkeypatch, tmp_path)

    db_file = tmp_path / "copy.db"
    db_file.write_text("conversations")

    from src.api.main import app

    with TestClient(app) as client:
        res = client.get("/admin/security/investigate", params={"path": str(db_file)})
        assert res.status_code == 403
