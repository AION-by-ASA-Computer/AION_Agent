"""Orchestration API auth: JWT + session ownership."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.api.auth_login import ChatAuthIdentity
from src.api.orchestration import _assert_session_owner, orchestration_auth


@pytest.mark.anyio
async def test_orchestration_auth_rejects_anonymous_when_password_auth(monkeypatch):
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    with pytest.raises(HTTPException) as exc:
        await orchestration_auth(x_aion_orch_secret=None, auth=ChatAuthIdentity(via="anonymous"))
    assert exc.value.status_code == 401


@pytest.mark.anyio
async def test_orchestration_auth_accepts_valid_secret(monkeypatch):
    monkeypatch.setenv("AION_ORCHESTRATION_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv("AION_ORCHESTRATION_SECRET_AUTH", "1")
    auth = await orchestration_auth(
        x_aion_orch_secret="test-secret",
        auth=ChatAuthIdentity(via="anonymous"),
    )
    assert auth.via == "orch_secret"


@pytest.mark.anyio
async def test_assert_session_owner_forbidden_for_other_user(monkeypatch):
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    class _Row:
        def first(self):
            return ("alice",)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=_Row())
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = None

    with patch("src.api.orchestration.get_async_session_maker", return_value=lambda: mock_cm):
        with pytest.raises(HTTPException) as exc:
            await _assert_session_owner(
                "sess-1",
                ChatAuthIdentity(via="chat_token", identifier="bob"),
            )
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_assert_session_owner_allows_orch_secret():
    await _assert_session_owner(
        "sess-1",
        ChatAuthIdentity(via="orch_secret", identifier="internal"),
    )


def test_v1_chat_stream_accepts_session_id_alias():
    from src.api.v1.chat import ChatStreamBody

    body = ChatStreamBody.model_validate(
        {
            "session_id": "fc5b65b1-24ac-4da5-8ec2-cf8d645e57ef",
            "message": "hello",
            "profile": "aion_std",
        }
    )
    assert body.conversation_id == "fc5b65b1-24ac-4da5-8ec2-cf8d645e57ef"
