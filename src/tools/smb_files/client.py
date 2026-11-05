"""Thin wrapper over ``smbclient`` (smbprotocol): sessions and error mapping.

Connections are opened lazily on the first tool call (never at import or at
``list_tools``) because the MCP process also starts with empty/mock
credentials during admin probes.  Every low-level failure is converted into a
stable error code so tools return JSON errors instead of raising.
"""

from __future__ import annotations

import logging
import socket
from typing import Tuple

from src.tools.smb_files import auth_guard
from src.tools.smb_files.credentials import SmbCredentials
from src.tools.smb_files.settings_store import SmbConfig

logger = logging.getLogger("aion.smb_files.client")

CONNECT_TIMEOUT = 15  # seconds; the LAN server either answers fast or is down


class SmbError(Exception):
    """Operation failed; ``code`` is the stable tool error code."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# NTSTATUS -> error code for file operations (logon codes live in auth_guard).
_STATUS_CODES = {
    0xC0000022: "access_denied",
    0xC0000043: "access_denied",  # sharing violation: file locked by another user
    0xC0000034: "not_found",
    0xC000003A: "not_found",
    0xC000000F: "not_found",
    0xC00000CC: "not_found",  # bad network name = share does not exist
    0xC0000035: "already_exists",
    0xC000007F: "too_large",  # disk full
}


def map_exception(exc: BaseException) -> Tuple[str, str]:
    """Translate any exception to ``(code, message)`` without leaking secrets."""
    if isinstance(exc, SmbError):
        return exc.code, exc.message
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        status &= 0xFFFFFFFF
        if status in auth_guard.LOGON_STATUSES:
            return auth_guard.LOGON_STATUSES[status], "Windows login failed."
        if status in _STATUS_CODES:
            return _STATUS_CODES[status], f"SMB status 0x{status:08x}."
    if isinstance(exc, FileNotFoundError):
        return "not_found", "Path not found."
    if isinstance(exc, FileExistsError):
        return "already_exists", "Path already exists."
    if isinstance(exc, PermissionError):
        return "access_denied", "Access denied by the file server."
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout", "The file server did not answer in time."
    if isinstance(exc, OSError):
        return "unreachable", "The file server is not reachable."
    return "error", f"Unexpected error: {type(exc).__name__}"


def open_session(cfg: SmbConfig, creds: SmbCredentials) -> None:
    """Register the SMB session for this user (idempotent, cached by smbclient).

    Consults the auth guard first so already-rejected credentials never reach
    the server; records a block on the first logon failure.
    """
    blocked = auth_guard.check(creds.username, creds.password, cfg.lockout_minutes)
    if blocked:
        raise SmbError(*blocked)
    import smbclient  # lazy: keeps import/list_tools free of network libs

    try:
        smbclient.register_session(
            cfg.host,
            username=creds.username,
            password=creds.password,
            port=cfg.port,
            encrypt=cfg.require_encryption or None,
            connection_timeout=CONNECT_TIMEOUT,
            auth_protocol=cfg.auth_protocol,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a stable code below
        code, msg = map_exception(exc)
        if code in auth_guard.LOGON_CODES:
            auth_guard.record_failure(code, creds.username, creds.password)
        raise SmbError(code, msg) from exc
    auth_guard.clear()
