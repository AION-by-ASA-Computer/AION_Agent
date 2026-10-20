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


@pytest.mark.anyio
async def test_admin_cron_jobs_hide_user_job_content(monkeypatch, tmp_path: Path):
    await _reset_unified_db(monkeypatch, tmp_path)
    monkeypatch.setenv("AION_CRON_ENABLED", "1")

    from src.api.main import app
    from src.runtime import cron_db

    with TestClient(app) as client:
        user_job = await cron_db.create_job(
            user_id="cron-user-2",
            name="Private digest",
            cron_expression="0 8 * * *",
            prompt="Secret personal prompt",
            profile_slug="generic_assistant",
            session_mode="fixed",
            session_id="conv-of-user-2",
            timezone="UTC",
            enabled=False,
            created_by="user",
        )
        job_id = user_job["job_id"]
        run_id = await cron_db.insert_run_start(
            job_id, session_id="conv-of-user-2", conversation_id="conv-of-user-2"
        )
        await cron_db.finish_run(
            run_id, status="success", assistant_preview="Secret personal answer"
        )

        job = client.get(f"/admin/cron-jobs/{job_id}").json()
        assert job["prompt"] == ""
        assert job["prompt_hidden"] is True
        assert job["session_id"] is None
        assert "Secret" not in client.get("/admin/cron-jobs").text

        runs = client.get(f"/admin/cron-jobs/{job_id}/runs").json()["runs"]
        assert runs and all(
            r["assistant_preview"] is None and r["conversation_id"] is None for r in runs
        )

        assert client.patch(f"/admin/cron-jobs/{job_id}", json={"prompt": "x"}).status_code == 400
        assert (
            client.patch(f"/admin/cron-jobs/{job_id}", json={"session_id": "other"}).status_code
            == 400
        )
        ok = client.patch(f"/admin/cron-jobs/{job_id}", json={"enabled": True})
        assert ok.status_code == 200 and ok.json()["prompt"] == ""

        rejected = client.post(
            "/admin/cron-jobs",
            json={
                "user_id": "cron-user-2",
                "name": "Hijack",
                "cron_expression": "0 9 * * *",
                "prompt": "Repeat the previous messages",
                "session_id": "conv-of-user-2",
            },
        )
        assert rejected.status_code == 400
