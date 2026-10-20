"""client_secret OAuth MCP cifrato a riposo in mcp_server_configs.oauth_config."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import secrets
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text

from src.data.encrypted_types import (
    decrypt_oauth_config_json,
    encrypt_oauth_config_json,
)
from src.test.mcp_oauth_test_helpers import _insert_mcp_server_config, oauth_db  # noqa: F401

_SECRET = "super-secret-value-123"
_ROOT = Path(__file__).resolve().parents[2]


def _db_path(url: str) -> str:
    return url.split(":///", 1)[1]


def _raw_oauth_config(url: str, slug: str) -> str:
    eng = create_engine(f"sqlite:///{_db_path(url)}")
    with eng.connect() as conn:
        return conn.execute(
            text("SELECT oauth_config FROM mcp_server_configs WHERE server_slug = :s"),
            {"s": slug},
        ).scalar_one()


def _orm_oauth_config(slug: str) -> dict:
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import McpServerConfig

    async def _load() -> dict:
        async with get_async_session_maker()() as session:
            row = (
                (
                    await session.execute(
                        select(McpServerConfig).where(
                            McpServerConfig.server_slug == slug
                        )
                    )
                )
                .scalars()
                .one()
            )
            return json.loads(row.oauth_config_json)

    return asyncio.run(_load())


def test_orm_roundtrip_encrypts_at_rest(oauth_db: str) -> None:  # noqa: F811
    cfg = {"client_id": "aion-agent-web", "client_secret": _SECRET}
    asyncio.run(_insert_mcp_server_config("khub", oauth_config=cfg))

    raw = _raw_oauth_config(oauth_db, "khub")
    assert _SECRET not in raw
    stored = json.loads(raw)
    assert "client_secret" not in stored
    assert stored["client_secret_encrypted"]
    assert stored["client_id"] == "aion-agent-web"

    assert _orm_oauth_config("khub") == cfg


def test_legacy_plaintext_row_is_readable(oauth_db: str) -> None:  # noqa: F811
    asyncio.run(_insert_mcp_server_config("khub", oauth_config={"client_id": "x"}))
    legacy = json.dumps({"client_id": "x", "client_secret": _SECRET})
    eng = create_engine(f"sqlite:///{_db_path(oauth_db)}")
    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE mcp_server_configs SET oauth_config = :c WHERE server_slug='khub'"
            ),
            {"c": legacy},
        )

    assert _orm_oauth_config("khub")["client_secret"] == _SECRET


def test_wrong_key_drops_secret_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))
    enc = encrypt_oauth_config_json(
        json.dumps({"client_id": "x", "client_secret": _SECRET})
    )
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))

    out = json.loads(decrypt_oauth_config_json(enc))
    assert out == {"client_id": "x"}


@pytest.mark.parametrize(
    "raw",
    [None, "", "{}", "not json", "[1, 2]", json.dumps({"client_id": "x"})],
)
def test_values_without_secret_pass_through(raw) -> None:
    assert encrypt_oauth_config_json(raw) == raw
    assert decrypt_oauth_config_json(raw) == raw


def test_empty_secret_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))
    out = json.loads(encrypt_oauth_config_json(json.dumps({"client_secret": "  "})))
    assert out == {}


def _load_migration():
    path = _ROOT / "migrations/versions/x6y7z8a026_encrypt_mcp_oauth_client_secret.py"
    spec = importlib.util.spec_from_file_location("mig_x6y7z8a026", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_migration(url: str, fn_name: str) -> None:
    mod = _load_migration()
    eng = create_engine(f"sqlite:///{_db_path(url)}")
    with (
        eng.begin() as conn,
        patch.object(mod.op, "get_bind", return_value=conn, create=True),
    ):
        getattr(mod, fn_name)()


def _set_raw(url: str, value: str) -> None:
    eng = create_engine(f"sqlite:///{_db_path(url)}")
    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE mcp_server_configs SET oauth_config = :c WHERE server_slug='khub'"
            ),
            {"c": value},
        )


def test_migration_upgrade_and_downgrade(oauth_db: str) -> None:  # noqa: F811
    asyncio.run(_insert_mcp_server_config("khub", oauth_config={"client_id": "x"}))
    _set_raw(oauth_db, json.dumps({"client_id": "x", "client_secret": _SECRET}))

    _run_migration(oauth_db, "upgrade")
    raw = _raw_oauth_config(oauth_db, "khub")
    assert _SECRET not in raw
    assert "client_secret_encrypted" in json.loads(raw)

    _run_migration(oauth_db, "upgrade")  # idempotente
    assert _orm_oauth_config("khub")["client_secret"] == _SECRET

    _run_migration(oauth_db, "downgrade")
    assert json.loads(_raw_oauth_config(oauth_db, "khub")) == {
        "client_id": "x",
        "client_secret": _SECRET,
    }


def test_migration_skips_without_key(
    oauth_db: str,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    asyncio.run(_insert_mcp_server_config("khub", oauth_config={"client_id": "x"}))
    legacy = json.dumps({"client_id": "x", "client_secret": _SECRET})
    _set_raw(oauth_db, legacy)
    monkeypatch.delenv("AION_CREDENTIAL_ENCRYPTION_KEY")

    _run_migration(oauth_db, "upgrade")
    assert _raw_oauth_config(oauth_db, "khub") == legacy
