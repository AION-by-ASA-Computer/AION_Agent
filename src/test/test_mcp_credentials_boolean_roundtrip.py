"""Round-trip of boolean (toggle) MCP credentials saved from the Integrations page.

The chat-ui dialog saves toggles as "true"/"false" with a display hint
("Attivo"/"Disattivo") and, since the value is encrypted, rebuilds the toggle
from that hint on reload. These tests cover the backend half of that loop:

- ``parse_boolean_token`` matches tokens exactly ("disattivo" is NOT true; the
  old substring check ``"attivo" in hint`` reloaded every saved false as true);
- ``POST /integrations/credentials`` accepts JSON booleans, stores the string
  value and a hint consistent with it, for both on and off, and for flips;
- the integrations list re-exposes a saved custom boolean variable (not in the
  admin schema) as a ``boolean`` field instead of a masked password field.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any, Dict

import pytest

from src.api.auth_login import ChatAuthIdentity
from src.data.bootstrap import ensure_bootstrap_schema
from src.data.engine import get_async_session_maker, init_engine
from src.data.ids import new_uuid7_str
from src.data.models import McpServerConfig
from src.runtime import credential_store as cs
from src.runtime.mcp_integration_helpers import (
    integration_row_to_public_dict,
    parse_boolean_token,
)

SLUG = "bool-mcp"
USER = "alice"


@pytest.fixture()
def bool_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Fresh SQLite DB with user credentials enabled and one per-user MCP server.

    The server declares a boolean field ``ENABLE_SSL`` (default "true") in its
    admin schema; runtime cache invalidation is stubbed out (no MCP pools here).
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'bool.db'}"
    monkeypatch.setenv("AION_DB_URL", url)
    monkeypatch.setenv("AION_MCP_USER_CREDENTIALS", "1")
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))
    import src.data.engine as eng_mod

    eng_mod._engine = None  # type: ignore[attr-defined]
    eng_mod._session_factory = None  # type: ignore[attr-defined]
    eng = init_engine(url)
    asyncio.run(ensure_bootstrap_schema(eng))

    async def _noop_invalidate(*_a: Any, **_kw: Any) -> None:
        return None

    import src.runtime.mcp_credential_invalidate as inv_mod

    monkeypatch.setattr(inv_mod, "invalidate_mcp_credentials_runtime", _noop_invalidate)

    schema = [
        {
            "key": "ENABLE_SSL",
            "label": "Enable SSL",
            "type": "boolean",
            "required": False,
            "default_value": "true",
        }
    ]

    async def _seed() -> None:
        async with get_async_session_maker()() as session:
            session.add(
                McpServerConfig(
                    id=new_uuid7_str(),
                    server_slug=SLUG,
                    display_name="Bool MCP",
                    is_enabled_for_users=True,
                    requires_user_credentials=True,
                    credential_mode="per_user",
                    credential_schema_json=json.dumps(schema),
                )
            )
            await session.commit()

    asyncio.run(_seed())
    return url


def _auth() -> ChatAuthIdentity:
    """Authenticated chat identity (mutations refuse anonymous callers)."""
    return ChatAuthIdentity(identifier=USER, via="chat_token")


async def _save(credentials: Dict[str, Any], hints: Dict[str, str] | None) -> None:
    """Call the save endpoint exactly as the chat-ui dialog does."""
    from src.api.v1.mcp_integrations import CredentialSetBody, save_credentials

    body = CredentialSetBody(
        server_slug=SLUG, credentials=credentials, display_hints=hints
    )
    await save_credentials(body, auth=_auth())


async def _public() -> Dict[str, Any]:
    """Integration as returned to the chat-ui list (schema + credential hints)."""
    async with get_async_session_maker()() as session:
        from sqlalchemy import select

        row = (
            (
                await session.execute(
                    select(McpServerConfig).where(McpServerConfig.server_slug == SLUG)
                )
            )
            .scalars()
            .one()
        )
    from src.api.v1.mcp_integrations import _credential_user_id

    return await integration_row_to_public_dict(
        row, user_id=_credential_user_id(_auth()), tenant_id="default", anonymous=False
    )


def _hint(pub: Dict[str, Any], key: str) -> Any:
    """Display hint for ``key`` in a public integration dict (None if absent)."""
    return next(
        (h["display_hint"] for h in pub["credentials_hints"] if h["key"] == key), None
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Attivo", True),
        ("Disattivo", False),  # regression: substring "attivo" made this True
        ("disattivo", False),
        ("true", True),
        ("FALSE", False),
        (True, True),
        (False, False),
        ("0", False),
        ("on", True),
        ("Attivo (true)", None),
        ("****", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_boolean_token_exact_match(raw: Any, expected: Any) -> None:
    """Boolean hints/values are parsed by exact token, never by substring."""
    assert parse_boolean_token(raw) is expected


@pytest.mark.parametrize("value", ["false", "true"])
def test_boolean_credential_roundtrip(bool_db: str, value: str) -> None:
    """Saving a toggle on/off persists the string value and a matching hint."""

    async def run() -> None:
        hint = "Attivo" if value == "true" else "Disattivo"
        await _save({"ENABLE_SSL": value}, {"ENABLE_SSL": hint})

        stored = await cs.get_credential(
            _credential_user_id_for_test(), SLUG, "ENABLE_SSL"
        )
        assert stored == value
        pub = await _public()
        assert _hint(pub, "ENABLE_SSL") == hint
        # The value the UI rebuilds from the hint matches what was saved.
        assert parse_boolean_token(_hint(pub, "ENABLE_SSL")) is (value == "true")

    asyncio.run(run())


def _credential_user_id_for_test() -> str:
    """User id the endpoint stores credentials under (sanitised identifier)."""
    from src.api.v1.mcp_integrations import _credential_user_id

    return _credential_user_id(_auth())


def test_boolean_credential_flip_on_off_on(bool_db: str) -> None:
    """Flipping a toggle repeatedly always reloads the last saved state."""

    async def run() -> None:
        for value in ("true", "false", "true", "false"):
            hint = "Attivo" if value == "true" else "Disattivo"
            await _save({"ENABLE_SSL": value}, {"ENABLE_SSL": hint})
            pub = await _public()
            assert parse_boolean_token(_hint(pub, "ENABLE_SSL")) is (value == "true")
            stored = await cs.get_credential(
                _credential_user_id_for_test(), SLUG, "ENABLE_SSL"
            )
            assert stored == value

    asyncio.run(run())


def test_json_boolean_payload_is_coerced(bool_db: str) -> None:
    """A JSON ``false`` (not the string) is accepted and stored as "false"."""

    async def run() -> None:
        await _save({"ENABLE_SSL": False, "IMAP_PORT": 993}, None)
        uid = _credential_user_id_for_test()
        assert await cs.get_credential(uid, SLUG, "ENABLE_SSL") == "false"
        assert await cs.get_credential(uid, SLUG, "IMAP_PORT") == "993"
        pub = await _public()
        # No hint sent: the backend derives the canonical boolean one...
        assert _hint(pub, "ENABLE_SSL") == "Disattivo"
        # ...but never for non-boolean values.
        assert _hint(pub, "IMAP_PORT") is None

    asyncio.run(run())


def test_inconsistent_boolean_hint_is_corrected(bool_db: str) -> None:
    """A stale boolean hint disagreeing with the value is rewritten to match it."""

    async def run() -> None:
        await _save({"ENABLE_SSL": "false"}, {"ENABLE_SSL": "Attivo"})
        assert _hint(await _public(), "ENABLE_SSL") == "Disattivo"

    asyncio.run(run())


def test_text_hint_is_not_rewritten(bool_db: str) -> None:
    """Text/secret previews are kept even when the value looks boolean."""

    async def run() -> None:
        await _save(
            {"SOME_TEXT": "true", "API_TOKEN": "false", "RETRIES": "0"},
            {"SOME_TEXT": "true", "API_TOKEN": "****", "RETRIES": "0"},
        )
        pub = await _public()
        assert _hint(pub, "SOME_TEXT") == "true"
        assert _hint(pub, "API_TOKEN") == "****"
        assert _hint(pub, "RETRIES") == "0"

    asyncio.run(run())


def test_custom_boolean_variable_reloads_as_toggle(bool_db: str) -> None:
    """A custom toggle (not in the admin schema) comes back as a boolean field."""

    async def run() -> None:
        await _save(
            {"MY_FLAG": "false", "MY_SECRET": "s3cr3t"},
            {"MY_FLAG": "Disattivo", "MY_SECRET": "****"},
        )
        pub = await _public()
        fields = {f["key"]: f for f in pub["credential_schema"]}
        assert fields["MY_FLAG"]["type"] == "boolean"
        # Label is the key, not the value preview ("Disattivo"/"****").
        assert fields["MY_FLAG"]["label"] == "MY_FLAG"
        assert fields["MY_SECRET"]["type"] == "password"
        assert fields["MY_SECRET"]["label"] == "MY_SECRET"
        # The admin-schema toggle is still there with its own type.
        assert fields["ENABLE_SSL"]["type"] == "boolean"

    asyncio.run(run())
