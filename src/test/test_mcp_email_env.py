"""Email MCP env normalization and tool argument sanitization."""
from __future__ import annotations

from src.mcp_manager import normalize_mcp_email_server_env, sanitize_mcp_tool_arguments


def test_sanitize_none_strings_to_null() -> None:
    args = {
        "account_name": "default",
        "before": "None",
        "since": "",
        "flagged": "null",
        "answered": None,
        "seen": False,
    }
    clean = sanitize_mcp_tool_arguments(args)
    assert "before" not in clean
    assert "since" not in clean
    assert "flagged" not in clean
    assert "answered" not in clean
    assert clean["seen"] is False



def test_normalize_email_env_port_587_starttls() -> None:
    env = {
        "MCP_EMAIL_SERVER_SMTP_PORT": "587",
        "MCP_EMAIL_SERVER_IMAP_VERIFY_SSL": "false",
    }
    out = normalize_mcp_email_server_env(env)
    assert out["MCP_EMAIL_SERVER_IMAP_SSL"] == "false"
    assert out["MCP_EMAIL_SERVER_SMTP_START_SSL"] == "true"
    assert out["MCP_EMAIL_SERVER_SMTP_SSL"] == "false"
