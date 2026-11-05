"""File operations on SMB shares, as plain functions returning JSON-able dicts.

Each public function is what one MCP tool calls.  They never raise: success is
``{"ok": True, ...}`` and any failure is ``{"ok": False, "error": <code>,
"message": ...}`` (same style as ``ocr_mcp``/``stt_mcp``), so the agent always
gets an actionable message.  Safety rules enforced here:

* every path goes through :func:`paths.resolve_path` (server + share
  allowlist, no ``..``), and the target's server picks the credential set;
* writes are refused on read-only shares and never overwrite unless asked;
* there is intentionally NO delete operation (SMB has no recycle bin);
* sizes are capped by the admin limits; logs carry user/op/path only, never
  file contents or passwords.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import stat as stat_mod
import time
from typing import Any, Callable, Dict, List, Optional

from src.tools.smb_files import client
from src.tools.smb_files.client import SmbError
from src.tools.smb_files.credentials import CredentialsMissing, load_credentials
from src.tools.smb_files.extract import extract_text
from src.tools.smb_files.paths import PathError, SmbTarget, resolve_path
from src.tools.smb_files.settings_store import SmbConfig, SmbServer

logger = logging.getLogger("aion.smb_files.ops")

_MB = 1024 * 1024
_CHUNK = 1024 * 1024
_UNSAFE_NAME = re.compile(r"[^a-zA-Z0-9._\-]")


def _smb():
    """Return the ``smbclient`` module (indirection so tests can mock it)."""
    import smbclient

    return smbclient


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


def _guarded(
    op: str, cfg: Optional[SmbConfig], path: str, fn: Callable[[], Dict]
) -> Dict:
    """Run ``fn`` with uniform error mapping and a structured audit log line."""
    user = os.environ.get("AION_CURRENT_USER_ID", "?")
    try:
        if cfg is None:
            raise SmbError(
                "not_configured",
                "The file server is not configured by the administrator.",
            )
        result = fn()
        logger.info("smb_op user=%s op=%s path=%s ok=True", user, op, path)
        return result
    except CredentialsMissing as exc:
        code, msg = "credentials_missing", str(exc)
    except PathError as exc:
        code, msg = exc.code, exc.message
    except Exception as exc:  # noqa: BLE001 - converted to a tool error
        code, msg = client.map_exception(exc)
    logger.info("smb_op user=%s op=%s path=%s ok=False error=%s", user, op, path, code)
    return _error(code, msg)


def _connect(cfg: SmbConfig, server: SmbServer):
    """Open the user's session on ``server`` (guard + lazy connect) and return smbclient."""
    client.open_session(server, load_credentials(server), cfg.lockout_minutes)
    return _smb()


def _check_writable(target: SmbTarget) -> None:
    if target.read_only:
        raise SmbError("share_read_only", f"Share '{target.share}' is read-only.")


def _entry(name: str, st) -> Dict[str, Any]:
    is_dir = stat_mod.S_ISDIR(st.st_mode)
    return {
        "name": name,
        "type": "dir" if is_dir else "file",
        "size": None if is_dir else st.st_size,
        "modified": int(st.st_mtime),
    }


def list_shares(cfg: Optional[SmbConfig]) -> Dict[str, Any]:
    """Servers and shares the admin made available (no network access needed).

    ``path`` of each share is the prefix the agent must use in the other tools.
    """
    if cfg is None:
        return _error(
            "not_configured", "The file server is not configured by the administrator."
        )
    return {
        "ok": True,
        "servers": [
            {
                "server": srv.alias,
                "label": srv.label,
                "host": srv.host,
                "shares": [
                    {
                        "name": s.name,
                        "path": f"{srv.alias}/{s.name}",
                        "label": s.label,
                        "read_only": s.read_only,
                    }
                    for s in srv.shares
                ],
            }
            for srv in cfg.servers
        ],
    }


def list_dir(cfg: Optional[SmbConfig], path: str, limit: int = 200) -> Dict[str, Any]:
    """List one directory (non recursive), directories first."""

    def run() -> Dict:
        t = resolve_path(path, cfg)
        smb = _connect(cfg, t.server)
        entries = []
        for e in smb.scandir(t.unc):
            entries.append(_entry(e.name, e.stat()))
        entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
        return {
            "ok": True,
            "path": t.display,
            "read_only": t.read_only,
            "total": len(entries),
            "truncated": len(entries) > limit,
            "entries": entries[:limit],
        }

    return _guarded("list_dir", cfg, path, run)


def stat(cfg: Optional[SmbConfig], path: str) -> Dict[str, Any]:
    """Metadata of a file or directory."""

    def run() -> Dict:
        t = resolve_path(path, cfg)
        st = _connect(cfg, t.server).stat(t.unc)
        return {
            "ok": True,
            "path": t.display,
            "read_only": t.read_only,
            **_entry(os.path.basename(t.rel) or t.share, st),
        }

    return _guarded("stat", cfg, path, run)


def search(
    cfg: Optional[SmbConfig],
    path: str,
    pattern: str,
    max_depth: int = 4,
    max_results: int = 50,
    time_budget_s: float = 20.0,
) -> Dict[str, Any]:
    """Find names matching a glob/substring below ``path`` with hard limits.

    Depth, result count and wall-clock budget keep a search on a huge share
    from hanging the agent; ``truncated`` tells it the scan was cut short.
    """

    def run() -> Dict:
        t = resolve_path(path, cfg)
        smb = _connect(cfg, t.server)
        pat = pattern if any(c in pattern for c in "*?[") else f"*{pattern}*"
        deadline = time.monotonic() + time_budget_s
        found: List[Dict] = []
        truncated = False
        stack = [(t.unc, t.rel, 0)]
        while stack and not truncated:
            unc, rel, depth = stack.pop()
            for e in smb.scandir(unc):
                if time.monotonic() > deadline or len(found) >= max_results:
                    truncated = True
                    break
                child_rel = f"{rel}\\{e.name}" if rel else e.name
                st = e.stat()
                if fnmatch.fnmatch(e.name.lower(), pat.lower()):
                    item = _entry(e.name, st)
                    rel = child_rel.replace(chr(92), "/")
                    item["path"] = f"{t.server.alias}/{t.share}/{rel}"
                    found.append(item)
                if stat_mod.S_ISDIR(st.st_mode) and depth < max_depth:
                    stack.append((f"{unc}\\{e.name}", child_rel, depth + 1))
        return {"ok": True, "results": found, "truncated": truncated}

    return _guarded("search", cfg, path, run)


def _size_of(smb, target: SmbTarget) -> int:
    st = smb.stat(target.unc)
    if stat_mod.S_ISDIR(st.st_mode):
        raise SmbError("is_directory", "The path is a directory, not a file.")
    return st.st_size


def _read_bytes(smb, target: SmbTarget, limit_mb: int) -> bytes:
    size = _size_of(smb, target)
    if size > limit_mb * _MB:
        raise SmbError(
            "too_large", f"File is {size} bytes; the limit is {limit_mb} MB."
        )
    with smb.open_file(target.unc, mode="rb") as fh:
        return fh.read()


def read_file(
    cfg: Optional[SmbConfig], path: str, max_chars: int = 20000, offset_chars: int = 0
) -> Dict[str, Any]:
    """Read a file as text (PDF/DOCX/XLSX/CSV/txt), paginated by characters."""

    def run() -> Dict:
        t = resolve_path(path, cfg)
        data = _read_bytes(_connect(cfg, t.server), t, cfg.max_read_mb)
        out = extract_text(data, os.path.basename(t.rel), max_chars, offset_chars)
        return {"ok": True, "path": t.display, **out}

    return _guarded("read_file", cfg, path, run)


def _session_id() -> str:
    sid = os.environ.get("AION_CHAT_SESSION_ID", "").strip()
    if not sid:
        raise SmbError("no_session", "No chat session is available for the workspace.")
    return sid


def copy_to_session(
    cfg: Optional[SmbConfig], path: str, dest_name: Optional[str] = None
) -> Dict[str, Any]:
    """Copy a file into the session workspace (for OCR/sandbox processing)."""

    def run() -> Dict:
        from src.session_workspace import safe_resolve

        t = resolve_path(path, cfg)
        data = _read_bytes(_connect(cfg, t.server), t, cfg.max_read_mb)
        name = _UNSAFE_NAME.sub("_", dest_name or os.path.basename(t.rel) or "file")
        dest = safe_resolve(_session_id(), f"workspace/smb/{name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {
            "ok": True,
            "path": t.display,
            "session_path": f"workspace/smb/{name}",
            "size": len(data),
        }

    return _guarded("copy_to_session", cfg, path, run)


def _exists(smb, unc: str) -> bool:
    try:
        smb.stat(unc)
        return True
    except Exception as exc:  # noqa: BLE001
        if client.map_exception(exc)[0] == "not_found":
            return False
        raise


def _write(smb, t: SmbTarget, data: bytes, overwrite: bool, limit_mb: int) -> Dict:
    """Shared tail of the two write tools: checks, then write the bytes."""
    _check_writable(t)
    if not t.rel:
        raise PathError("invalid_path", "Specify a file path inside the share.")
    if len(data) > limit_mb * _MB:
        raise SmbError(
            "too_large", f"Content is {len(data)} bytes; the limit is {limit_mb} MB."
        )
    existed = _exists(smb, t.unc)
    if existed and not overwrite:
        raise SmbError(
            "already_exists", "File exists. Ask the user before using overwrite=True."
        )
    with smb.open_file(t.unc, mode="wb") as fh:
        for i in range(0, len(data), _CHUNK):
            fh.write(data[i : i + _CHUNK])
    return {"ok": True, "path": t.display, "size": len(data), "overwritten": existed}


def write_text(
    cfg: Optional[SmbConfig], path: str, content: str, overwrite: bool = False
) -> Dict[str, Any]:
    """Create (or, with ``overwrite``, replace) a UTF-8 text file."""

    def run() -> Dict:
        t = resolve_path(path, cfg)
        return _write(
            _connect(cfg, t.server),
            t,
            content.encode("utf-8"),
            overwrite,
            cfg.max_write_mb,
        )

    return _guarded("write_text", cfg, path, run)


def upload_from_session(
    cfg: Optional[SmbConfig], path: str, session_path: str, overwrite: bool = False
) -> Dict[str, Any]:
    """Upload a file from the session workspace to a share."""

    def run() -> Dict:
        from src.session_workspace import safe_resolve

        t = resolve_path(path, cfg)
        try:
            src = safe_resolve(_session_id(), session_path, must_exist=True)
        except (ValueError, FileNotFoundError) as exc:
            raise SmbError(
                "session_file_not_found", f"Session file invalid: {exc}"
            ) from exc
        if not src.is_file():
            raise SmbError("session_file_not_found", "Session path is not a file.")
        return _write(
            _connect(cfg, t.server), t, src.read_bytes(), overwrite, cfg.max_write_mb
        )

    return _guarded("upload_from_session", cfg, path, run)


def mkdir(cfg: Optional[SmbConfig], path: str, parents: bool = True) -> Dict[str, Any]:
    """Create a directory (idempotent when ``parents`` is true)."""

    def run() -> Dict:
        t = resolve_path(path, cfg)
        _check_writable(t)
        if not t.rel:
            raise PathError("invalid_path", "Specify a folder path inside the share.")
        smb = _connect(cfg, t.server)
        if parents:
            smb.makedirs(t.unc, exist_ok=True)
        else:
            smb.mkdir(t.unc)
        return {"ok": True, "path": t.display}

    return _guarded("mkdir", cfg, path, run)


def move(
    cfg: Optional[SmbConfig], src: str, dst: str, overwrite: bool = False
) -> Dict[str, Any]:
    """Rename/move within the same share of the same server.

    No cross-share or cross-server moves: they would need a copy + delete.
    """

    def run() -> Dict:
        s, d = resolve_path(src, cfg), resolve_path(dst, cfg)
        if s.server.alias != d.server.alias or s.share.lower() != d.share.lower():
            raise SmbError(
                "cross_share_move",
                "Moving between shares or servers is not supported.",
            )
        _check_writable(s)
        if not s.rel or not d.rel:
            raise PathError("invalid_path", "Cannot move a share root.")
        smb = _connect(cfg, s.server)
        if _exists(smb, d.unc) and not overwrite:
            raise SmbError(
                "already_exists",
                "Destination exists. Ask the user before overwrite=True.",
            )
        # smbclient.replace overwrites; rename fails on an existing target.
        (smb.replace if overwrite else smb.rename)(s.unc, d.unc)
        return {"ok": True, "from": s.display, "to": d.display}

    return _guarded("move", cfg, f"{src} -> {dst}", run)
