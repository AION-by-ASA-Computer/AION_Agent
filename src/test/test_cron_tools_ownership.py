"""Cron built-in tools enforce per-user ownership."""

from pathlib import Path

import pytest

from src.runtime import cron_db
from src.runtime.cron_tools import _get_scheduled_job
from src.test.test_api_endpoints import _reset_unified_db


@pytest.mark.anyio
async def test_get_scheduled_job_denies_other_user(monkeypatch, tmp_path: Path):
    await _reset_unified_db(monkeypatch, tmp_path)
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_engine

    await ensure_bootstrap_schema(get_engine())
    monkeypatch.setenv("AION_CRON_ENABLED", "1")
    job = await cron_db.create_job(
        user_id="owner-a",
        name="Daily",
        cron_expression="0 8 * * *",
        prompt="Say hello",
        profile_slug="generic_assistant",
        created_by="test",
    )
    msg = await _get_scheduled_job(job["job_id"], "other-b")
    assert "another user" in msg.lower()
    await cron_db.delete_job(job["job_id"])
