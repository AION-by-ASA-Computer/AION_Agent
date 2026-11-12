"""Windows credentials of the current user, read from the MCP process env.

The credential store injects them at spawn time (see ``resolve_mcp_env_for_user``):

* credential set ``DEFAULT`` -> ``SMB_USERNAME`` / ``SMB_PASSWORD``;
* any other set ``<SET>`` (servers in another domain) -> keys
  ``SMB_USERNAME__<SET>`` / ``SMB_PASSWORD__<SET>`` inside the JSON object of
  ``SMB_EXTRA_CREDENTIALS`` (the ``${AION_USER_SMB_FILES__*}`` wildcard
  placeholder, because the set names come from the admin configuration and
  cannot be listed statically in the registry).

The admin probe and unconfigured users get empty or mock values, so those must
be detected *before* any network call: otherwise a fake password would count as
a failed logon against Active Directory and contribute to locking someone's
account.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

from src.tools.smb_files.settings_store import DEFAULT_CREDENTIAL_SET, SmbServer

# Values produced by ``generate_probe_mock_value`` for these variable names.
_MOCK_VALUES = frozenset({"probe_user", "probe_secret_key", "probe_test_val"})
EXTRA_ENV = "SMB_EXTRA_CREDENTIALS"


class CredentialsMissing(Exception):
    """No real credentials available for this user."""


@dataclass(frozen=True)
class SmbCredentials:
    """``username`` is in ``DOMAIN\\user`` form when a domain is known."""

    username: str
    password: str
    credential_set: str = DEFAULT_CREDENTIAL_SET


def credential_keys(credential_set: str) -> tuple[str, str]:
    """Credential-store keys ``(username, password)`` of a credential set."""
    if credential_set == DEFAULT_CREDENTIAL_SET:
        return "SMB_USERNAME", "SMB_PASSWORD"
    return f"SMB_USERNAME__{credential_set}", f"SMB_PASSWORD__{credential_set}"


def normalize_username(raw: str, default_domain: str = "") -> str:
    """Accept ``DOM\\user``, ``user@dom`` or bare ``user`` (+ default domain).

    ``user@dom`` is rewritten to ``DOM\\user`` so NTLM always receives an
    explicit domain; a bare name falls back to the server's default domain.
    """
    name = (raw or "").strip()
    if "\\" in name:
        dom, _, user = name.partition("\\")
        return f"{dom.strip()}\\{user.strip()}"
    if "@" in name:
        user, _, dom = name.rpartition("@")
        # UPN suffix is a DNS name; NTLM wants the NetBIOS-style first label.
        return f"{dom.split('.')[0].upper()}\\{user.strip()}"
    return f"{default_domain.strip()}\\{name}" if default_domain.strip() else name


def _extra_credentials(src) -> Dict[str, str]:
    """Parse ``SMB_EXTRA_CREDENTIALS``; anything but a JSON object counts as empty."""
    raw = src.get(EXTRA_ENV) or ""
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}  # probe mock or garbage: behave as "not configured"
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}


def load_credentials(server: SmbServer, env: Optional[dict] = None) -> SmbCredentials:
    """Read and normalise the user's credentials for ``server`` or raise ``CredentialsMissing``."""
    src = os.environ if env is None else env
    user_key, pass_key = credential_keys(server.credential_set)
    if server.credential_set == DEFAULT_CREDENTIAL_SET:
        user = (src.get(user_key) or "").strip()
        password = src.get(pass_key) or ""
    else:
        extra = _extra_credentials(src)
        user = (extra.get(user_key) or "").strip()
        password = extra.get(pass_key) or ""
    if not user or not password or user in _MOCK_VALUES or password in _MOCK_VALUES:
        which = (
            "Windows credentials"
            if server.credential_set == DEFAULT_CREDENTIAL_SET
            else f"Windows credentials for '{server.credential_set}'"
        )
        raise CredentialsMissing(
            f"{which} (needed for server '{server.alias}') are not configured. Ask "
            "the user to enter them in 'My integrations' (never in the chat)."
        )
    return SmbCredentials(
        normalize_username(user, server.default_domain),
        password,
        server.credential_set,
    )
