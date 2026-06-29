import asyncio
import secrets
from pathlib import Path

import pytest

from src.data.bootstrap import ensure_bootstrap_schema
from src.data.engine import init_engine
from src.runtime import credential_store as cs


@pytest.fixture()
def iso_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'iso.db'}"
    monkeypatch.setenv("AION_DB_URL", url)
    monkeypatch.setenv("AION_MCP_USER_CREDENTIALS", "1")
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))
    import src.data.engine as eng_mod

    eng_mod._engine = None  # type: ignore[attr-defined]
    eng_mod._session_factory = None  # type: ignore[attr-defined]
    eng = init_engine(url)
    asyncio.run(ensure_bootstrap_schema(eng))
    return url


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))
    raw = "my-secret-token-123"
    enc = cs.encrypt_value(raw)
    assert enc != raw
    assert cs.decrypt_value(enc) == raw


def test_user_credential_isolation(iso_db: str) -> None:
    async def run() -> None:
        await cs.set_credential("alice", "email_mcp", "ACCESS_TOKEN", "alice-token")
        await cs.set_credential("bob", "email_mcp", "ACCESS_TOKEN", "bob-token")
        a = await cs.get_credential("alice", "email_mcp", "ACCESS_TOKEN")
        b = await cs.get_credential("bob", "email_mcp", "ACCESS_TOKEN")
        assert a == "alice-token"
        assert b == "bob-token"
        assert a != b

    asyncio.run(run())


def test_resolve_hyphenated_server_slug_from_env_placeholder(iso_db: str) -> None:
    """${AION_USER_EMAIL_MCP_SERVER__*} must resolve credentials stored as email-mcp-server."""

    async def run() -> None:
        await cs.set_credential(
            "alice",
            "email-mcp-server",
            "EMAIL_USER",
            "alice@example.com",
        )
        resolved = await cs.resolve_user_credential_string(
            "${AION_USER_EMAIL_MCP_SERVER__EMAIL_USER}",
            user_id="alice",
            tenant_id="default",
            server_slug="email-mcp-server",
        )
        assert resolved == "alice@example.com"

    asyncio.run(run())


def test_mcp_home_isolation_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AION_MCP_USER_HOME_ISOLATION", "1")
    from src.mcp_manager import _apply_mcp_home_isolation

    env: dict = {}
    _apply_mcp_home_isolation(env, "alice@test")
    home = Path(env["HOME"])
    assert home.is_dir()
    assert (home / ".config").is_dir()
    assert "mcp_home" in str(home)
