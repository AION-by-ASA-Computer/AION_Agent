"""AS metadata discovery order, DCR retry on stale endpoint, admin oauth_config merge."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from src.api import admin as admin_mod
from src.api.v1 import mcp_integrations as mod
from src.mcp_credential_discovery import authorization_server_metadata_urls

ISSUER = "https://khub.example.com/keycloak/realms/khub"
NATIVE_REG = f"{ISSUER}/clients-registrations/openid-connect"
PROXY_REG = "https://khub.example.com/register"


def test_metadata_urls_path_issuer_follow_rfc8414_order() -> None:
    assert authorization_server_metadata_urls(ISSUER) == [
        "https://khub.example.com/.well-known/oauth-authorization-server/keycloak/realms/khub",
        "https://khub.example.com/.well-known/openid-configuration/keycloak/realms/khub",
        f"{ISSUER}/.well-known/openid-configuration",
        f"{ISSUER}/.well-known/oauth-authorization-server",
    ]


def test_metadata_urls_root_issuer() -> None:
    assert authorization_server_metadata_urls("https://as.example.com/") == [
        "https://as.example.com/.well-known/oauth-authorization-server",
        "https://as.example.com/.well-known/openid-configuration",
    ]


def test_dynamic_registration_retries_with_rediscovered_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AION_MCP_OAUTH_DYNAMIC_REGISTRATION", "1")
    calls: List[str] = []

    async def fake_post(*, server_slug: str, reg_endpoint: str, redirect_uri: str):
        calls.append(reg_endpoint)
        if reg_endpoint == PROXY_REG:
            return {"client_id": "dyn-123", "client_secret": "s3cret"}
        return None  # Keycloak "Trusted Hosts" 403

    as_meta = {
        "issuer": ISSUER,
        "authorization_endpoint": "https://khub.example.com/authorize",
        "token_endpoint": "https://khub.example.com/token",
        "registration_endpoint": PROXY_REG,
    }
    oauth_cfg: Dict[str, Any] = {
        "authorization_server": ISSUER,
        "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
        "token_url": f"{ISSUER}/protocol/openid-connect/token",
        "registration_endpoint": NATIVE_REG,
    }
    with (
        patch.object(mod, "_oauth_post_client_registration", side_effect=fake_post),
        patch(
            "src.mcp_credential_discovery.fetch_authorization_server_metadata",
            return_value=as_meta,
        ),
        patch("src.runtime.mcp_oauth_audit.log_dynamic_client_registration"),
    ):
        ok = asyncio.run(
            mod._oauth_dynamic_client_register(
                server_slug="khub",
                oauth_cfg=oauth_cfg,
                redirect_uri="http://localhost:8001/v1/integrations/oauth/callback",
            )
        )

    assert ok is True
    assert calls == [NATIVE_REG, PROXY_REG]
    assert oauth_cfg["client_id"] == "dyn-123"
    assert oauth_cfg["client_secret"] == "s3cret"
    assert oauth_cfg["client_id_source"] == "dynamic_registration"
    assert oauth_cfg["registration_endpoint"] == PROXY_REG
    assert oauth_cfg["authorization_endpoint"] == "https://khub.example.com/authorize"
    assert oauth_cfg["token_url"] == "https://khub.example.com/token"


def test_dynamic_registration_no_retry_when_endpoint_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AION_MCP_OAUTH_DYNAMIC_REGISTRATION", "1")
    calls: List[str] = []

    async def fake_post(*, server_slug: str, reg_endpoint: str, redirect_uri: str):
        calls.append(reg_endpoint)
        return None

    oauth_cfg = {"authorization_server": ISSUER, "registration_endpoint": PROXY_REG}
    with (
        patch.object(mod, "_oauth_post_client_registration", side_effect=fake_post),
        patch(
            "src.mcp_credential_discovery.fetch_authorization_server_metadata",
            return_value={"registration_endpoint": PROXY_REG},
        ),
    ):
        ok = asyncio.run(
            mod._oauth_dynamic_client_register(
                server_slug="khub",
                oauth_cfg=oauth_cfg,
                redirect_uri="http://localhost:8001/v1/integrations/oauth/callback",
            )
        )
    assert ok is False
    assert calls == [PROXY_REG]
    assert "client_id" not in oauth_cfg


def test_admin_oauth_config_masks_secret() -> None:
    out = admin_mod._oauth_config_for_admin(
        json.dumps({"client_id": "abc", "client_secret": "top"})
    )
    assert out["client_id"] == "abc"
    assert out["client_secret"] == ""
    assert out["client_secret_set"] is True


def test_admin_merge_keeps_secret_and_discovered_endpoints() -> None:
    stored = json.dumps(
        {
            "authorization_server": ISSUER,
            "authorization_endpoint": "https://khub.example.com/authorize",
            "registration_endpoint": PROXY_REG,
            "token_url": "https://khub.example.com/token",
            "client_id": "manual",
            "client_secret": "top",
        }
    )
    merged = admin_mod._merge_admin_oauth_config(
        stored,
        {
            "provider": "generic",
            "authorization_server": ISSUER,
            "token_url": "",
            "client_id": "manual",
            "client_secret": "",
            "client_secret_set": True,
            "scopes": [],
        },
    )
    assert merged["client_secret"] == "top"
    assert merged["token_url"] == "https://khub.example.com/token"
    assert merged["authorization_endpoint"] == "https://khub.example.com/authorize"
    assert "client_secret_set" not in merged


def test_admin_merge_new_client_id_drops_old_secret_and_source() -> None:
    stored = json.dumps(
        {
            "authorization_server": ISSUER,
            "client_id": "dyn-1",
            "client_secret": "old",
            "client_id_source": "dynamic_registration",
        }
    )
    merged = admin_mod._merge_admin_oauth_config(
        stored,
        {"authorization_server": ISSUER, "client_id": "manual", "client_secret": ""},
    )
    assert merged["client_id"] == "manual"
    assert "client_secret" not in merged
    assert "client_id_source" not in merged

    merged = admin_mod._merge_admin_oauth_config(
        stored,
        {"authorization_server": ISSUER, "client_id": "manual", "client_secret": "new"},
    )
    assert merged["client_secret"] == "new"


def test_admin_merge_cleared_client_id_reverts_to_dynamic() -> None:
    stored = json.dumps(
        {"authorization_server": ISSUER, "client_id": "m", "client_secret": "s"}
    )
    merged = admin_mod._merge_admin_oauth_config(
        stored, {"authorization_server": ISSUER, "client_id": "", "client_secret": ""}
    )
    assert "client_id" not in merged
    assert "client_secret" not in merged


def test_admin_merge_changed_auth_server_resets_discovery() -> None:
    stored = json.dumps(
        {
            "authorization_server": ISSUER,
            "authorization_endpoint": "https://khub.example.com/authorize",
            "registration_endpoint": PROXY_REG,
            "client_id": "dyn-1",
            "client_id_source": "dynamic_registration",
        }
    )
    merged = admin_mod._merge_admin_oauth_config(
        stored,
        {"authorization_server": "https://other.example.com", "client_id": "dyn-1"},
    )
    assert merged["authorization_server"] == "https://other.example.com"
    assert "authorization_endpoint" not in merged
    assert "registration_endpoint" not in merged
    assert "client_id" not in merged


def test_admin_merge_empty_payload_resets() -> None:
    assert admin_mod._merge_admin_oauth_config(json.dumps({"client_id": "x"}), {}) == {}


# --- OAuth disconnect ---------------------------------------------------------

from src.api.auth_login import ChatAuthIdentity  # noqa: E402


def _alice() -> ChatAuthIdentity:
    return ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")


async def _stored_keys(user_id: str, slug: str) -> List[str]:
    from src.runtime.credential_store import list_credentials_hints

    return sorted(h["key"] for h in await list_credentials_hints(user_id, slug))


def test_oauth_disconnect_removes_refresh_token_and_is_idempotent(
    oauth_db: str,
) -> None:
    from src.runtime.credential_store import set_credential

    user_id = mod._credential_user_id(_alice())

    async def scenario() -> None:
        await set_credential(user_id, "khub", "OAUTH_TOKEN", "at")
        await set_credential(user_id, "khub", "OAUTH_REFRESH_TOKEN", "rt")
        with patch(
            "src.runtime.mcp_credential_invalidate.invalidate_mcp_credentials_runtime",
            new=AsyncMock(return_value=1),
        ):
            first = await mod.delete_user_credential(
                "khub", "OAUTH_TOKEN", auth=_alice()
            )
            assert first == {"ok": True}
            assert await _stored_keys(user_id, "khub") == []
            second = await mod.delete_user_credential(
                "khub", "OAUTH_TOKEN", auth=_alice()
            )
            assert second["ok"] is True and second["already_disconnected"] is True

    asyncio.run(scenario())


def test_oauth_disconnect_survives_runtime_invalidation_error(oauth_db: str) -> None:
    from src.runtime.credential_store import set_credential

    user_id = mod._credential_user_id(_alice())

    async def scenario() -> None:
        await set_credential(user_id, "khub", "OAUTH_TOKEN", "at")
        with patch(
            "src.runtime.mcp_credential_invalidate.invalidate_mcp_credentials_runtime",
            new=AsyncMock(side_effect=RuntimeError("cancel scope in a different task")),
        ):
            out = await mod.delete_user_credential("khub", "OAUTH_TOKEN", auth=_alice())
        assert out == {"ok": True}
        assert await _stored_keys(user_id, "khub") == []

    asyncio.run(scenario())


def test_delete_missing_non_oauth_credential_still_404(oauth_db: str) -> None:
    from fastapi import HTTPException

    async def scenario() -> None:
        with pytest.raises(HTTPException) as exc:
            await mod.delete_user_credential("khub", "API_KEY", auth=_alice())
        assert exc.value.status_code == 404

    asyncio.run(scenario())


def test_oauth_redirect_callback_clears_integrations_cache(oauth_db: str) -> None:
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock

    from src.test.mcp_oauth_test_helpers import insert_mcp_server_config

    asyncio.run(
        insert_mcp_server_config(
            "khub", oauth_config={"token_url": "https://khub.example.com/token"}
        )
    )
    mod._INTEGRATIONS_CACHE["alice:default"] = (0.0, {"integrations": ["stale"]})
    mod._oauth_pending["st"] = {
        "server_slug": "khub",
        "code_verifier": "v",
        "user_id": "alice",
        "redirect_uri": "http://localhost:8001/v1/integrations/oauth/callback",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    request = MagicMock()
    request.url.scheme = "http"
    request.headers = {"host": "localhost:8001"}
    with (
        patch.object(
            mod,
            "_resolve_oauth_config_for_server",
            new=AsyncMock(return_value={"token_url": "https://khub.example.com/token"}),
        ),
        patch(
            "src.runtime.oauth_token_exchange.exchange_authorization_code",
            new=AsyncMock(return_value={"access_token": "at"}),
        ),
        patch.object(mod, "persist_oauth_token_response", new=AsyncMock()),
        patch.object(mod, "set_user_mcp_preference", new=AsyncMock()),
    ):
        resp = asyncio.run(
            mod.oauth_callback_redirect(code="c", state="st", request=request)
        )

    assert "oauth_status=success" in resp.headers["location"]
    assert mod._INTEGRATIONS_CACHE == {}
