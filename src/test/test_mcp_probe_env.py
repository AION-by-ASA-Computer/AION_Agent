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


def test_badly_formatted_authorization_is_auth_failure():
    classified = classify_mcp_error(
        "bad request: Authorization header is badly formatted"
    )
    assert classified["error_type"] == "auth_failed"
