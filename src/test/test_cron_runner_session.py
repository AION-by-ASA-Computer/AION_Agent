"""Session resolution for scheduled job runs."""

from pathlib import Path

import pytest

from src.runtime import cron_db
from src.runtime.cron_runner import resolve_session_for_run
from src.test.test_api_endpoints import _reset_unified_db


@pytest.mark.anyio
async def test_resolve_session_new_mode_generates_uuid(monkeypatch, tmp_path: Path):
    await _reset_unified_db(monkeypatch, tmp_path)
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_engine

    await ensure_bootstrap_schema(get_engine())
    job = {
        "job_id": "j1",
        "session_mode": "new",
        "session_id": "old-should-not-use",
    }
    sid = await resolve_session_for_run(job)
    assert sid != "old-should-not-use"
    assert len(sid) >= 32


@pytest.mark.anyio
async def test_resolve_session_fixed_uses_existing(monkeypatch, tmp_path: Path):
    await _reset_unified_db(monkeypatch, tmp_path)
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_engine

    await ensure_bootstrap_schema(get_engine())
    job = await cron_db.create_job(
        user_id="u1",
        name="Fixed",
        cron_expression="0 9 * * *",
        prompt="ping",
        profile_slug="generic_assistant",
        session_mode="fixed",
        session_id="sess-abc-123",
        created_by="test",
    )
    sid = await resolve_session_for_run(job)
    assert sid == "sess-abc-123"
    await cron_db.delete_job(job["job_id"])


@pytest.mark.anyio
async def test_resolve_session_fixed_creates_and_persists_when_missing(
    monkeypatch, tmp_path: Path
):
    await _reset_unified_db(monkeypatch, tmp_path)
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_engine

    await ensure_bootstrap_schema(get_engine())
    job = await cron_db.create_job(
        user_id="u1",
        name="Fixed empty",
        cron_expression="0 9 * * *",
        prompt="ping",
        profile_slug="generic_assistant",
        session_mode="fixed",
        session_id=None,
        created_by="test",
    )
    sid1 = await resolve_session_for_run(job)
    assert sid1
    refreshed = await cron_db.get_job(job["job_id"])
    assert refreshed and refreshed.get("session_id") == sid1
    sid2 = await resolve_session_for_run(refreshed)
    assert sid2 == sid1
    await cron_db.delete_job(job["job_id"])
