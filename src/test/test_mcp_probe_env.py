"""Admin MCP probe must not send a fake bearer token."""

from src.runtime.credential_store import normalize_inline_secret
from src.runtime.mcp_health import classify_mcp_error, merge_probe_env


def test_unresolved_oauth_secret_is_not_mocked():
    template = {
        "OAUTH_TOKEN": "${AION_USER_GITHUB__OAUTH_TOKEN}",
        "AION_USER_GITHUB__OAUTH_TOKEN": "${AION_USER_GITHUB__OAUTH_TOKEN}",
    }
    env, missing = merge_probe_env(template, resolved={})
    assert "OAUTH_TOKEN" in missing
    assert "AION_USER_GITHUB__OAUTH_TOKEN" in missing
    assert "probe_secret_key" not in env.values()
    assert env == {}


def test_resolved_oauth_token_drops_bearer_prefix():
    template = {
        "AION_USER_GITHUB__OAUTH_TOKEN": "${AION_USER_GITHUB__OAUTH_TOKEN}",
    }
    env, missing = merge_probe_env(
        template,
        resolved={"AION_USER_GITHUB__OAUTH_TOKEN": "Bearer gho_real_token"},
    )
    assert missing == []
    assert env["AION_USER_GITHUB__OAUTH_TOKEN"] == "gho_real_token"


def test_non_secret_placeholder_still_uses_a_mock():
    template = {"IMAP_HOST": "${AION_USER_EMAIL__IMAP_HOST}"}
    env, missing = merge_probe_env(template, resolved={})
    assert missing == []
    assert env["IMAP_HOST"] == "imap.example.com"


def test_normalize_inline_secret_only_for_bearer_keys():
    assert (
        normalize_inline_secret("Bearer gho_abc", cred_key="OAUTH_TOKEN") == "gho_abc"
    )
    assert (
        normalize_inline_secret("Bearer gho_abc", cred_key="IMAP_PASSWORD")
        == "Bearer gho_abc"
    )


def test_missing_user_oauth_points_to_connect():
    classified = classify_mcp_error(
        "credenziali mancanti per ms365 (MS365_MCP_OAUTH_TOKEN)"
    )
    assert classified["error_type"] == "auth_failed"
    assert "Connetti" in classified["hint"]


def test_ms365_oauth_token_fills_process_env():
    import asyncio

    from src.runtime import credential_store as store

    async def fake_get(
        user_id,
        server_slug,
        key,
        *,
        tenant_id="default",
        auto_refresh_oauth=True,
    ):
        if key == "OAUTH_TOKEN" and server_slug == "ms365":
            return "graph-access-token"
        return None

    async def run():
        original = store.get_credential
        store.get_credential = fake_get
        try:
            return await store.resolve_mcp_env_for_user(
                {
                    "MS365_MCP_OAUTH_TOKEN": (
                        "${AION_USER_MS365__MS365_MCP_OAUTH_TOKEN}"
                    )
                },
                user_id="alice",
                tenant_id="default",
                server_slug="ms365",
            )
        finally:
            store.get_credential = original

    env = asyncio.run(run())
    assert env["MS365_MCP_OAUTH_TOKEN"] == "graph-access-token"


def test_badly_formatted_authorization_is_auth_failure():
    classified = classify_mcp_error(
        "bad request: Authorization header is badly formatted"
    )
    assert classified["error_type"] == "auth_failed"
