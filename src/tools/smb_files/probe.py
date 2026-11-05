"""Admin connection test for the SMB file server ("Testa connessione" in admin-ui).

Called by ``POST /admin/smb/test`` (``src/api/admin_smb.py``) through
``asyncio.to_thread`` because smbprotocol is blocking.  Two levels:

* without credentials: TCP connect + SMB2/3 negotiate only, which proves the
  host/port are right and the server speaks a supported dialect;
* with credentials (typed by the admin for this test only, never stored or
  logged): also session setup and a tree connect to every configured share,
  reporting the outcome per share.

Uses the low-level smbprotocol objects instead of ``smbclient`` on purpose: the
test must not leave a session in smbclient's global pool, and it must not use
``auth_guard`` (that relies on the per-user MCP HOME, absent in the backend).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from src.tools.smb_files.client import CONNECT_TIMEOUT, map_exception
from src.tools.smb_files.credentials import normalize_username
from src.tools.smb_files.settings_store import SmbConfig

logger = logging.getLogger("aion.smb_files.probe")


def _dialect_label(dialect: Any) -> Optional[str]:
    """Render the negotiated dialect (e.g. ``0x0311`` -> ``"3.1.1"``)."""
    if not isinstance(dialect, int):
        return None
    return f"{dialect >> 8}.{(dialect >> 4) & 0xF}.{dialect & 0xF}"


def _error_code(exc: BaseException) -> str:
    """Stable error code for the test result (never includes credentials)."""
    from smbprotocol.exceptions import SMBAuthenticationError

    # Local SPNEGO/NTLM failure before the server answers (e.g. negotiate
    # without a usable mechanism): report it as an authentication problem.
    if isinstance(exc, SMBAuthenticationError):
        return "auth_failed"
    return map_exception(exc)[0]


def _safe_disconnect(obj: Any, **kwargs: Any) -> None:
    """Best-effort teardown: a failing disconnect must not hide the real result."""
    if obj is None:
        return
    try:
        obj.disconnect(**kwargs)
    except Exception:  # noqa: BLE001 - cleanup only
        pass


def test_connection(
    cfg: SmbConfig, username: Optional[str] = None, password: Optional[str] = None
) -> Dict[str, Any]:
    """Probe the configured server; returns a JSON-serialisable result.

    Result keys: ``ok``, ``error`` (code of the first blocking failure),
    ``negotiated``, ``dialect``, ``authenticated`` (``None`` without
    credentials) and ``shares`` (``[{name, ok, error}]``, only with
    credentials).  ``ok`` with credentials means every share was reachable.
    """
    # Lazy import: keeps the backend import path free of the SMB stack until a test runs.
    from smbprotocol.connection import Connection
    from smbprotocol.session import Session
    from smbprotocol.tree import TreeConnect

    result: Dict[str, Any] = {
        "ok": False,
        "error": None,
        "negotiated": False,
        "dialect": None,
        "authenticated": None,
        "shares": [],
    }
    with_creds = bool(username and password)
    conn = session = None
    try:
        # Step 1: TCP + negotiate (no credentials involved).
        conn = Connection(uuid.uuid4(), cfg.host, cfg.port)
        try:
            conn.connect(timeout=CONNECT_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - mapped to a code
            result["error"] = _error_code(exc)
            return result
        result["negotiated"] = True
        result["dialect"] = _dialect_label(getattr(conn, "dialect", None))
        if not with_creds:
            result["ok"] = True
            return result

        # Step 2: logon with the admin-supplied credentials (single attempt:
        # a wrong password counts against the AD lockout threshold).
        session = Session(
            conn,
            username=normalize_username(username or "", cfg.default_domain),
            password=password,
            require_encryption=cfg.require_encryption,
            auth_protocol=cfg.auth_protocol,
        )
        try:
            session.connect()
        except Exception as exc:  # noqa: BLE001 - mapped to a code
            result["authenticated"] = False
            result["error"] = _error_code(exc)
            return result
        result["authenticated"] = True

        # Step 3: every allowed share must be reachable with these credentials.
        shares: List[Dict[str, Any]] = []
        for share in cfg.shares:
            tree = TreeConnect(session, rf"\\{cfg.host}\{share.name}")
            try:
                tree.connect()
                shares.append({"name": share.name, "ok": True, "error": None})
            except Exception as exc:  # noqa: BLE001 - reported per share
                shares.append(
                    {"name": share.name, "ok": False, "error": _error_code(exc)}
                )
            finally:
                _safe_disconnect(tree)
        result["shares"] = shares
        failed = next((s for s in shares if not s["ok"]), None)
        result["ok"] = failed is None
        result["error"] = failed["error"] if failed else None
        return result
    finally:
        _safe_disconnect(session)
        _safe_disconnect(conn, close=True)
        logger.info(
            "smb test host=%s ok=%s error=%s with_credentials=%s",
            cfg.host,
            result["ok"],
            result["error"],
            with_creds,
        )
