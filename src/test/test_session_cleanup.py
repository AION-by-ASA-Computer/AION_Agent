"""Unit tests for automatic session cleanup and retention policy."""

import pytest
from datetime import datetime, timedelta, timezone

from src.data.engine import get_async_session_maker, init_engine
from src.data.bootstrap import ensure_bootstrap_schema
from src.data.migrations import run_migrations
from src.data.models import Conversation
from src.runtime.session_cleanup import (
    _session_cleanup_settings,
    cleanup_expired_sessions,
)


@pytest.mark.anyio
async def test_session_cleanup_settings_defaults(monkeypatch):
    monkeypatch.setenv("AION_SESSION_CLEANUP_MAX_AGE_DAYS", "15")
    monkeypatch.setenv("AION_SESSION_CLEANUP_INTERVAL_SEC", "86400")
    monkeypatch.setenv("AION_SESSION_CLEANUP_HARD_DELETE", "0")

    from src.settings import get_settings

    get_settings.cache_clear()

    days, interval, hard = _session_cleanup_settings()
    assert days == 15
    assert interval == 86400
    assert hard is False


@pytest.mark.anyio
async def test_cleanup_disabled(monkeypatch):
    res = await cleanup_expired_sessions(max_age_days=0)
    assert res.get("skipped") is True
    assert res.get("reason") == "disabled"


@pytest.mark.anyio
async def test_cleanup_soft_delete_archiving(tmp_path, monkeypatch):
    db_file = tmp_path / "test_session_cleanup_soft.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("AION_DB_URL", db_url)
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))

    eng = init_engine(db_url)
    await ensure_bootstrap_schema(eng)
    run_migrations()

    try:
        session_maker = get_async_session_maker()
        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=20)

        # Insert one old session and one fresh session
        async with session_maker() as session:
            old_conv = Conversation(
                id="test-old-soft-1",
                tenant_id="default",
                user_id="user1",
                profile_slug="aion_std",
                updated_at=old_date,
                created_at=old_date,
            )
            new_conv = Conversation(
                id="test-new-soft-1",
                tenant_id="default",
                user_id="user1",
                profile_slug="aion_std",
                updated_at=now,
                created_at=now,
            )
            session.add_all([old_conv, new_conv])
            await session.commit()

        # Run soft cleanup for > 15 days
        res = await cleanup_expired_sessions(max_age_days=15, hard_delete=False)
        assert res.get("processed_conversations") == 1
        assert "test-old-soft-1" in res.get("session_ids", [])

        # Check DB state
        async with session_maker() as session:
            c1 = await session.get(Conversation, "test-old-soft-1")
            c2 = await session.get(Conversation, "test-new-soft-1")
            assert c1 is not None
            assert c1.archived_at is not None
            assert c2 is not None
            assert c2.archived_at is None
    finally:
        await eng.dispose()


@pytest.mark.anyio
async def test_cleanup_hard_delete_and_sandbox(tmp_path, monkeypatch):
    db_file = tmp_path / "test_session_cleanup_hard.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("AION_DB_URL", db_url)
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))

    eng = init_engine(db_url)
    await ensure_bootstrap_schema(eng)
    run_migrations()

    try:
        session_maker = get_async_session_maker()
        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=30)

        # Create dummy sandbox directory on disk
        sandbox_dir = tmp_path / "sessions" / "test-old-hard-1"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        (sandbox_dir / "test_file.txt").write_text("hello sandbox", encoding="utf-8")
        assert (sandbox_dir / "test_file.txt").exists()

        # Insert old session
        async with session_maker() as session:
            old_conv = Conversation(
                id="test-old-hard-1",
                tenant_id="default",
                user_id="user1",
                profile_slug="aion_std",
                updated_at=old_date,
                created_at=old_date,
            )
            session.add(old_conv)
            await session.commit()

        # Run hard cleanup for > 15 days
        res = await cleanup_expired_sessions(max_age_days=15, hard_delete=True)
        assert res.get("processed_conversations", 0) >= 1
        assert "test-old-hard-1" in res.get("session_ids", [])

        # Check sandbox directory was deleted
        assert not sandbox_dir.exists()

        # Check DB record hard-deleted
        async with session_maker() as session:
            c1 = await session.get(Conversation, "test-old-hard-1")
            assert c1 is None
    finally:
        await eng.dispose()
