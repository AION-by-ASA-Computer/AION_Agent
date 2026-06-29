"""Admin cron-jobs HTTP API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.test.test_api_endpoints import _reset_unified_db


@pytest.mark.anyio
async def test_admin_cron_jobs_crud(monkeypatch, tmp_path: Path):
    await _reset_unified_db(monkeypatch, tmp_path)
    monkeypatch.setenv("AION_CRON_ENABLED", "1")

    from src.api.main import app

    with TestClient(app) as client:
        create = client.post(
            "/admin/cron-jobs",
            json={
                "user_id": "cron-user-1",
                "name": "Morning brief",
                "cron_expression": "0 9 * * *",
                "prompt": "Summarize inbox",
                "profile_slug": "generic_assistant",
                "session_mode": "new",
                "timezone": "UTC",
            },
        )
        assert create.status_code == 200, create.text
        job_id = create.json()["job_id"]

        listed = client.get("/admin/cron-jobs?user_id=cron-user-1")
        assert listed.status_code == 200
        assert any(j["job_id"] == job_id for j in listed.json()["jobs"])

        patched = client.patch(
            f"/admin/cron-jobs/{job_id}",
            json={"enabled": False},
        )
        assert patched.status_code == 200
        assert patched.json()["enabled"] is False

        deleted = client.delete(f"/admin/cron-jobs/{job_id}")
        assert deleted.status_code == 200
