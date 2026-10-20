"""Nessuno, admin inclusi, puo' vedere le chat di un altro utente.

Con password auth attiva l'identita' viene dal token: l'header
``X-AION-User-Id`` non basta a impersonare un utente, e ogni accesso alla
conversazione di un altro utente risponde 404.
"""

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.api.ownership import (
    assert_conversation_access,
    chat_user_id,
    effective_user_id,
    owned_by,
    read_session_owner_marker,
)
from src.data.history_bridge import UnifiedHistoryBridge


def _token(user: str, roles=None) -> ChatAuthIdentity:
    return ChatAuthIdentity(via="chat_token", identifier=user, roles=roles or [])


ALICE = _token("alice")
ADMIN = _token("root", roles=["admin"])


async def _reset(monkeypatch, tmp_path: Path) -> None:
    import src.data.engine as engine

    if engine._engine is not None:
        await engine._engine.dispose()
    engine._engine = None
    engine._session_factory = None
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "x" * 40)
    monkeypatch.delenv("AION_CHAT_UI_INTERNAL_SECRET", raising=False)
    from src.settings import get_settings

    get_settings.cache_clear()
    await UnifiedHistoryBridge().add_message(
        "conv-bob", "user", "segreto di bob", user_id="bob", message_id="m1"
    )


def _run(coro):
    return asyncio.run(coro)


def _assert_404(exc_info) -> None:
    assert exc_info.value.status_code == 404


# --- identita' effettiva ----------------------------------------------------


def test_chat_token_ignores_user_header():
    assert effective_user_id(ALICE, header_user_id="bob", body_user_id="bob") == "alice"
    assert _run(chat_user_id(auth=ALICE, x_aion_user_id="bob")) == "alice"


def test_header_trusted_only_in_open_mode_or_internal():
    anon = ChatAuthIdentity(via="anonymous")
    internal = ChatAuthIdentity(via="internal")
    assert effective_user_id(anon, header_user_id="bob") == "bob"
    assert effective_user_id(internal, header_user_id="bob") == "bob"


def test_api_key_is_its_own_principal():
    key = ChatAuthIdentity(via="api_key", identifier="k1", roles=["admin"])
    assert effective_user_id(key, header_user_id="bob", body_user_id="bob") == (
        "apikey_k1"
    )


def test_internal_secret_grants_no_admin(monkeypatch):
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "x" * 40)
    monkeypatch.setenv("AION_CHAT_UI_INTERNAL_SECRET", "s3cret")
    ident = _run(
        require_chat_auth(
            authorization=None,
            x_api_key=None,
            x_chat_ui_secret="s3cret",
            access_token=None,
        )
    )
    assert ident.via == "internal"
    assert "admin" not in (ident.roles or [])


# --- ownership --------------------------------------------------------------


def test_owner_access_and_cross_user_404(monkeypatch, tmp_path):
    async def run():
        await _reset(monkeypatch, tmp_path)
        assert await assert_conversation_access("conv-bob", "bob") is True
        for user in ("alice", "root"):
            with pytest.raises(HTTPException) as exc:
                await assert_conversation_access("conv-bob", user)
            _assert_404(exc)
            with pytest.raises(HTTPException) as exc:
                await assert_conversation_access(
                    "conv-bob", user, allow_missing=True, claim_if_missing=True
                )
            _assert_404(exc)

    _run(run())


def test_missing_session_needs_owner_marker(monkeypatch, tmp_path):
    async def run():
        await _reset(monkeypatch, tmp_path)
        with pytest.raises(HTTPException) as exc:
            await assert_conversation_access("conv-new", "alice")
        _assert_404(exc)

        await assert_conversation_access(
            "conv-new", "alice", allow_missing=True, claim_if_missing=True
        )
        assert read_session_owner_marker("conv-new") == "alice"
        assert await assert_conversation_access("conv-new", "alice") is False
        with pytest.raises(HTTPException) as exc:
            await assert_conversation_access(
                "conv-new", "bob", allow_missing=True, claim_if_missing=True
            )
        _assert_404(exc)

    _run(run())


def test_owned_by_checks_tenant_and_user():
    class Row:
        tenant_id = "default"
        user_id = "bob"

    assert owned_by(Row(), "default", "bob")
    assert not owned_by(Row(), "default", "alice")
    assert not owned_by(Row(), "other", "bob")
    assert not owned_by(None, "default", "bob")


# --- endpoint ---------------------------------------------------------------


def test_chat_ui_endpoints_404_for_other_user(monkeypatch, tmp_path):
    from src.api.chat_ui import (
        get_conversation_chat_ui,
        get_conversation_messages_chat_ui,
    )

    async def run():
        await _reset(monkeypatch, tmp_path)
        uid = await chat_user_id(auth=ALICE, x_aion_user_id="bob")
        with pytest.raises(HTTPException) as exc:
            await get_conversation_chat_ui("conv-bob", user_id=uid)
        _assert_404(exc)
        with pytest.raises(HTTPException) as exc:
            await get_conversation_messages_chat_ui("conv-bob", user_id=uid)
        _assert_404(exc)

    _run(run())


def test_session_files_404_for_other_user(monkeypatch, tmp_path):
    from src.api.session_uploads import (
        get_session_tool_ledger,
        list_session_files,
    )

    async def run():
        await _reset(monkeypatch, tmp_path)
        for auth in (ALICE, ADMIN):
            with pytest.raises(HTTPException) as exc:
                await list_session_files("conv-bob", _auth=auth, x_aion_user_id="bob")
            _assert_404(exc)
            with pytest.raises(HTTPException) as exc:
                await get_session_tool_ledger(
                    "conv-bob", _auth=auth, x_aion_user_id="bob"
                )
            _assert_404(exc)

    _run(run())


def test_cron_cannot_target_other_users_conversation(monkeypatch, tmp_path):
    from src.api.cron_user import _require_owned_session

    async def run():
        await _reset(monkeypatch, tmp_path)
        with pytest.raises(HTTPException) as exc:
            await _require_owned_session("conv-bob", "alice")
        _assert_404(exc)
        await _require_owned_session("conv-bob", "bob")

    _run(run())


def test_admin_ltm_user_scope_is_owner_only():
    from src.api.ltm_admin import _scope

    with pytest.raises(HTTPException) as exc:
        _scope("default", "user", "bob", ADMIN)
    _assert_404(exc)
    assert _scope("default", "user", "root", ADMIN) is not None
    assert _scope("default", "global", "x", ADMIN) is not None


def test_admin_diagnostics_file_skips_user_sessions(tmp_path):
    from src.api.admin_diagnostics import _is_diagnostic_session_file

    sessions = tmp_path / "sessions"
    assert not _is_diagnostic_session_file(
        sessions / "conv-bob" / "workspace" / "out.txt", sessions
    )
    assert _is_diagnostic_session_file(
        sessions / "smoke_case_1" / "workspace" / "out.txt", sessions
    )
    assert _is_diagnostic_session_file(tmp_path / "outputs" / "chart.png", sessions)
