"""``user_profile_access`` è indicizzata per ``users.id``: get_agent e cron (FIX-07)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import src.runtime.cron_tools as cron_tools
from src.agent_profile import ProfileNotFoundError
from src.api import cron_user
from src.api.auth_login import ChatAuthIdentity
from src.api.cron_schemas import ScheduledJobCreate
from src.api.profile_access import user_row_id_for
from src.main import get_agent
from src.runtime import cron_db
from src.test.test_api_endpoints import _reset_unified_db

ROW_ID = "row-7f3a"
IDENT = "Mario_Rossi"
ALLOWED = "coding_workspace"


@pytest.fixture
async def restricted_user(monkeypatch, tmp_path: Path) -> None:
    await _reset_unified_db(monkeypatch, tmp_path)
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_async_session_maker, get_engine
    from src.data.models import User, UserProfileAccess

    await ensure_bootstrap_schema(get_engine())
    async with get_async_session_maker()() as session:
        session.add(
            User(
                id=ROW_ID,
                tenant_id="default",
                identifier=IDENT,
                display_name="Mario",
                roles_json="[]",
            )
        )
        session.add(
            UserProfileAccess(user_id=ROW_ID, tenant_id="default", profile_slug=ALLOWED)
        )
        await session.commit()
    monkeypatch.setenv("AION_CRON_ENABLED", "1")


@pytest.mark.anyio
async def test_user_row_id_lookup(restricted_user) -> None:
    assert await user_row_id_for(IDENT) == ROW_ID
    assert await user_row_id_for(IDENT.lower()) == ROW_ID
    assert await user_row_id_for(ROW_ID) == ROW_ID
    # ``_`` non fa da jolly come in LIKE.
    assert await user_row_id_for("MarioXRossi") is None
    assert await user_row_id_for("default") is None


@pytest.mark.anyio
async def test_get_agent_denies_profile_by_identifier(restricted_user) -> None:
    with pytest.raises(ProfileNotFoundError):
        await get_agent("infra_sre", session_id="s-acc", user_id=IDENT)


@pytest.mark.anyio
async def test_cron_rest_create_enforces_profile(restricted_user) -> None:
    auth = ChatAuthIdentity(user_row_id=ROW_ID, identifier=IDENT, via="chat_token")
    body = ScheduledJobCreate(
        name="x", cron_expression="0 9 * * *", prompt="p", profile_slug="infra_sre"
    )
    with pytest.raises(HTTPException) as exc:
        await cron_user.create_my_cron_job(body, uid=IDENT, auth=auth)
    assert exc.value.status_code == 403
    assert await cron_db.count_jobs_for_user(IDENT) == 0


@pytest.mark.anyio
async def test_cron_tool_enforces_profile(restricted_user, monkeypatch) -> None:
    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(cron_tools, "register_job", noop)
    msg = await cron_tools._create_scheduled_job(
        "x", "0 9 * * *", "p", session_id="s1", user_id=IDENT, profile_slug="infra_sre"
    )
    assert "not allowed" in msg
    assert await cron_db.count_jobs_for_user(IDENT) == 0

    msg = await cron_tools._create_scheduled_job(
        "x", "0 9 * * *", "p", session_id="s1", user_id=IDENT, profile_slug=ALLOWED
    )
    assert msg.startswith("Created")
    (job,) = await cron_db.list_jobs(user_id=IDENT)
    assert job["profile_slug"] == ALLOWED

    msg = await cron_tools._update_scheduled_job(
        job["job_id"], IDENT, profile_slug="infra_sre"
    )
    assert "not allowed" in msg
    assert (await cron_db.get_job(job["job_id"]))["profile_slug"] == ALLOWED
