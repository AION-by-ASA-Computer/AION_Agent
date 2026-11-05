"""Windows credentials of the current user, read from the MCP process env.

The credential store injects ``SMB_USERNAME`` / ``SMB_PASSWORD`` at spawn time
(see ``resolve_mcp_env_for_user``).  The admin probe and unconfigured users get
empty or mock values, so those must be detected *before* any network call:
otherwise a fake password would count as a failed logon against Active
Directory and contribute to locking someone's account.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from src.tools.smb_files.settings_store import SmbConfig

# Values produced by ``generate_probe_mock_value`` for these variable names.
_MOCK_VALUES = frozenset({"probe_user", "probe_secret_key"})


class CredentialsMissing(Exception):
    """No real credentials available for this user."""


@dataclass(frozen=True)
class SmbCredentials:
    """``username`` is in ``DOMAIN\\user`` form when a domain is known."""

    username: str
    password: str


def normalize_username(raw: str, default_domain: str = "") -> str:
    """Accept ``DOM\\user``, ``user@dom`` or bare ``user`` (+ default domain).

    ``user@dom`` is rewritten to ``DOM\\user`` so NTLM always receives an
    explicit domain; a bare name falls back to the admin's default domain.
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


def load_credentials(cfg: SmbConfig, env: Optional[dict] = None) -> SmbCredentials:
    """Read and normalise the user's credentials or raise ``CredentialsMissing``."""
    src = os.environ if env is None else env
    user = (src.get("SMB_USERNAME") or "").strip()
    password = src.get("SMB_PASSWORD") or ""
    if not user or not password or user in _MOCK_VALUES or password in _MOCK_VALUES:
        raise CredentialsMissing(
            "Windows credentials not configured. Ask the user to enter them in "
            "'My integrations' (never in the chat)."
        )
    return SmbCredentials(normalize_username(user, cfg.default_domain), password)
