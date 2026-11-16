"""_redact_url_for_log: OAuth endpoint URLs are logged without credentials.

Covers the hardening for CodeQL py/clear-text-logging-sensitive-data (alert #672):
userinfo, query string and fragment never reach the logs; scheme, host, port and
path are kept so the log line is still useful for debugging.
"""

from __future__ import annotations

import pytest

from src.api.v1.mcp_integrations import _redact_url_for_log


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Plain endpoint is unchanged.
        ("https://auth.example.com/register", "https://auth.example.com/register"),
        # Credentials in userinfo are dropped.
        (
            "https://user:s3cret@auth.example.com/register",
            "https://auth.example.com/register",
        ),
        # Tokens in query/fragment are dropped; port is kept.
        (
            "https://auth.example.com:8443/oauth/reg?token=abc&x=1#frag",
            "https://auth.example.com:8443/oauth/reg",
        ),
        ("", ""),
    ],
)
def test_redact_url_for_log(raw: str, expected: str) -> None:
    """Only scheme://host[:port]/path survives redaction."""
    assert _redact_url_for_log(raw) == expected


def test_redact_url_for_log_invalid_port_uses_placeholder() -> None:
    """An unparseable URL is replaced by a placeholder, never echoed back."""
    out = _redact_url_for_log("https://user:pw@host:notaport/x")
    assert out == "<invalid-url>"
    assert "pw" not in out
