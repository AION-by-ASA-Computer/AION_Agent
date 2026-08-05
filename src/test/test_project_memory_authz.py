"""Authorization tests for project-scoped Mnemos REST API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.v1 import project_memory as pm


def _member_auth():
    return SimpleNamespace(identifier="member_user", user_row_id=1, roles=["user"])


def _outsider_auth():
    return SimpleNamespace(identifier="outsider_user", user_row_id=2, roles=["user"])


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(pm.router)
    return TestClient(app)


def test_non_member_gets_403_on_project_memory_read(client):
    slug = "secret-project"
    app = client.app
    app.dependency_overrides[pm.require_chat_auth] = lambda: _outsider_auth()
    with patch.object(
        pm.sql_query_memory,
        "check_user_project_access",
        new_callable=AsyncMock,
        return_value=f"Access denied to SQL QueryMemory project '{slug}'.",
    ):
        res = client.get(f"/project-memory/status?project={slug}")
    app.dependency_overrides.clear()
    assert res.status_code == 403


def test_non_member_gets_403_on_project_memory_write(client):
    slug = "secret-project"
    app = client.app
    app.dependency_overrides[pm.require_chat_auth] = lambda: _outsider_auth()
    body = {
        "session_id": "sess-1",
        "project": slug,
        "content": "Sensitive deploy target is prod-eu",
        "category": "fact",
        "importance": 4,
    }
    with patch.object(
        pm.sql_query_memory,
        "check_user_project_access",
        new_callable=AsyncMock,
        return_value=f"Access denied to SQL QueryMemory project '{slug}'.",
    ):
        res = client.post("/project-memory/notes", json=body)
    app.dependency_overrides.clear()
    assert res.status_code == 403


def test_non_member_gets_403_on_project_memory_delete(client):
    slug = "secret-project"
    app = client.app
    app.dependency_overrides[pm.require_chat_auth] = lambda: _outsider_auth()
    body = {"session_id": "sess-1", "note_id": 42}
    note = SimpleNamespace(scope_type="project", scope_key=slug, tenant_id="default")
    with (
        patch.object(
            pm.sql_query_memory,
            "check_user_project_access",
            new_callable=AsyncMock,
            return_value=f"Access denied to SQL QueryMemory project '{slug}'.",
        ),
        patch(
            "src.memory.mnemos.store.get_note",
            new_callable=AsyncMock,
            return_value=note,
        ),
    ):
        res = client.request("DELETE", "/project-memory/notes/42", json=body)
    app.dependency_overrides.clear()
    assert res.status_code == 403


def test_member_can_access_when_check_passes(client):
    slug = "team-project"
    app = client.app
    app.dependency_overrides[pm.require_chat_auth] = lambda: _member_auth()
    with (
        patch.object(
            pm.sql_query_memory,
            "check_user_project_access",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            pm,
            "project_memory_status",
            new_callable=AsyncMock,
            return_value={"project": slug, "active_notes": 0},
        ),
    ):
        res = client.get(f"/project-memory/status?project={slug}")
    app.dependency_overrides.clear()
    assert res.status_code == 200
    assert res.json()["project"] == slug
