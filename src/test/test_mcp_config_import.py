import asyncio
import pytest
import secrets
from pathlib import Path

from src.data.bootstrap import ensure_bootstrap_schema
from src.data.engine import init_engine
from src.runtime import credential_store as cs
from src.api.admin import _is_secret_key, _is_literal_secret


@pytest.fixture()
def test_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'test_admin.db'}"
    monkeypatch.setenv("AION_DB_URL", url)
    monkeypatch.setenv("AION_MCP_USER_CREDENTIALS", "1")
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))

    import src.data.engine as eng_mod

    eng_mod._engine = None
    eng_mod._session_factory = None

    eng = init_engine(url)
    asyncio.run(ensure_bootstrap_schema(eng))
    return url


def test_is_secret_key():
    assert _is_secret_key("API_KEY") is True
    assert _is_secret_key("CLICKUP_TOKEN") is True
    assert _is_secret_key("MY_PASSWORD") is True
    assert _is_secret_key("SECRET_VAL") is True
    assert _is_secret_key("AUTH_HEADER") is True
    assert _is_secret_key("PORT") is False
    assert _is_secret_key("COMMAND") is False


def test_is_literal_secret():
    assert _is_literal_secret("my-api-key-123") is True
    assert _is_literal_secret("${AION_USER_CLICKUP__CLICKUP_API_KEY}") is False
    assert _is_literal_secret("") is False
    assert _is_literal_secret(None) is False
    assert _is_literal_secret(12345) is False


def test_org_shared_fallback(test_db):
    async def run() -> None:
        # Save a credential under org_shared
        await cs.set_credential(
            "org_shared", "clickup", "CLICKUP_API_KEY", "org-shared-secret"
        )

        # Test resolving string for an anonymous/regular user
        resolved = await cs.resolve_user_credential_string(
            "${AION_USER_CLICKUP__CLICKUP_API_KEY}",
            user_id="user_123",
            tenant_id="default",
            server_slug="clickup",
        )
        assert resolved == "org-shared-secret"

        # Test resolving string when user overrides it
        await cs.set_credential(
            "user_123", "clickup", "CLICKUP_API_KEY", "user-specific-secret"
        )
        resolved_override = await cs.resolve_user_credential_string(
            "${AION_USER_CLICKUP__CLICKUP_API_KEY}",
            user_id="user_123",
            tenant_id="default",
            server_slug="clickup",
        )
        assert resolved_override == "user-specific-secret"

    asyncio.run(run())
