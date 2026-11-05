"""Local protection against Active Directory account lockout.

AD locks an account after a few bad passwords.  The agent may retry a failing
tool many times, so after the *first* logon failure we persist a marker and
refuse to contact the server again with the same credentials.

The marker lives in the per-user MCP HOME (``data/users/<uid>/mcp_home``), so
it is shared by every MCP process of that user (several open chats).  There is
one marker per *credential set*: AD locks the account, and one set is one
account, so a bad password for the servers of set ``A`` must not block the
servers of set ``B`` (another domain).  It stores only an HMAC fingerprint of
user+password with a random per-file salt, never the password.  When the user saves new credentials the fingerprint changes and
the block lifts by itself.  ``account_locked`` blocks expire after a window
because the lockout itself eventually expires on the server.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional, Tuple

MARKER_PREFIX = ".smb_auth_block"

# NTSTATUS -> error code.  Numeric values because smbprotocol's NtStatus
# lacks some of these constants.
LOGON_STATUSES = {
    0xC000006D: "auth_failed",  # STATUS_LOGON_FAILURE
    0xC0000234: "account_locked",  # STATUS_ACCOUNT_LOCKED_OUT
    0xC0000071: "password_expired",  # STATUS_PASSWORD_EXPIRED
    0xC0000224: "password_expired",  # STATUS_PASSWORD_MUST_CHANGE
    0xC0000072: "account_disabled",  # STATUS_ACCOUNT_DISABLED
}
LOGON_CODES = frozenset(LOGON_STATUSES.values())


def _marker_path(cred_set: str) -> Optional[Path]:
    """Marker of one credential set in the isolated HOME; ``None`` without HOME.

    ``cred_set`` is validated upstream (``[A-Z0-9]``), so it is safe in a file name.
    """
    home = os.environ.get("HOME") or ""
    return Path(home) / f"{MARKER_PREFIX}.{cred_set.lower()}.json" if home else None


def _fingerprint(salt: str, username: str, password: str) -> str:
    return hmac.new(
        salt.encode(), f"{username}\0{password}".encode(), hashlib.sha256
    ).hexdigest()


def record_failure(code: str, username: str, password: str, cred_set: str) -> None:
    """Persist the block after a logon failure (atomic write, mode 0600)."""
    path = _marker_path(cred_set)
    if path is None:
        return
    salt = secrets.token_hex(16)
    data = {
        "salt": salt,
        "fingerprint": _fingerprint(salt, username, password),
        "code": code,
        "at": time.time(),
    }
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)  # atomic: concurrent readers never see a partial file


def clear(cred_set: str) -> None:
    """Remove the block of one set (called after a successful logon)."""
    path = _marker_path(cred_set)
    if path is not None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def check(
    username: str, password: str, lockout_minutes: int, cred_set: str
) -> Optional[Tuple[str, str]]:
    """Return ``(code, message)`` if these exact credentials of ``cred_set`` are blocked."""
    path = _marker_path(cred_set)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        same = hmac.compare_digest(
            data["fingerprint"], _fingerprint(data["salt"], username, password)
        )
    except (OSError, ValueError, KeyError):
        return None  # unreadable marker: fail open rather than break the connector
    if not same:
        return None  # credentials were updated by the user: try again
    code = data.get("code", "auth_failed")
    expired = time.time() - float(data.get("at", 0)) > lockout_minutes * 60
    if code == "account_locked" and expired:
        clear(cred_set)  # the server-side lockout has presumably expired
        return None
    return code, (
        "Windows login was rejected earlier with these credentials and is not "
        "retried to avoid locking the account. Ask the user to update their "
        "Windows credentials in 'My integrations'."
    )
