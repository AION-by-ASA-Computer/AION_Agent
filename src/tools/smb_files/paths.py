"""Path parsing and sandboxing for SMB targets.

Turns whatever the agent passes (``server/Share/sub/file.txt`` or the UNC form
``\\\\host\\Share\\sub\\file.txt``) into a canonical, validated target.  This is
the single gate that enforces the admin allowlist: unknown servers, unknown
shares, administrative shares (``C$``, ``ADMIN$``, ``IPC$``...) and ``..``
traversal are rejected *before* any network call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.tools.smb_files.settings_store import SmbConfig, SmbServer

# Characters Windows forbids in file names (path separators handled separately).
_INVALID_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


class PathError(Exception):
    """Invalid or disallowed path; ``code`` is the tool error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SmbTarget:
    """A validated location: ``unc`` is what smbclient receives."""

    server: SmbServer
    share: str
    rel: str  # path inside the share, backslash separated, "" = share root
    read_only: bool

    @property
    def unc(self) -> str:
        base = f"\\\\{self.server.host}\\{self.share}"
        return f"{base}\\{self.rel}" if self.rel else base

    @property
    def display(self) -> str:
        """``server/Share/rel`` form shown back to the agent/user (reusable as input)."""
        rel = self.rel.replace(chr(92), "/")
        return f"{self.server.alias}/{self.share}/{rel}".rstrip("/")


def _aliases(cfg: SmbConfig) -> str:
    return ", ".join(s.alias for s in cfg.servers)


def resolve_path(raw: str, cfg: SmbConfig) -> SmbTarget:
    """Validate ``raw`` against ``cfg`` and return the canonical target.

    The first segment names the server: its alias (``fs01/Docs/a.txt``) or,
    in UNC form, its host (``\\\\fs01.corp.local\\Docs\\a.txt``).  Raises
    :class:`PathError` (``invalid_path``, ``server_not_allowed``,
    ``share_not_allowed``).
    """
    text = (raw or "").strip()
    if not text:
        raise PathError("invalid_path", "Empty path.")
    norm = text.replace("/", "\\")
    unc = norm.startswith("\\\\")
    parts = [p for p in (norm[2:] if unc else norm).split("\\") if p != ""]
    if not parts:
        raise PathError("invalid_path", "Path must start with a server alias.")

    # Resolve the server: UNC paths name the host, the short form the alias.
    server = cfg.server_by_host(parts[0]) if unc else cfg.server(parts[0])
    if server is None:
        raise PathError(
            "server_not_allowed",
            f"Unknown file server '{parts[0]}'. Use 'server/Share/path' with one "
            f"of: {_aliases(cfg)}.",
        )
    if len(parts) < 2:
        raise PathError(
            "invalid_path", "Path must include a share: 'server/Share/path'."
        )

    share_name, segments = parts[1], parts[2:]
    # Administrative/hidden shares are never reachable, even if an admin listed one.
    if share_name.endswith("$"):
        raise PathError(
            "share_not_allowed", "Administrative shares are not accessible."
        )
    share = server.share(share_name)
    if share is None:
        allowed = ", ".join(s.name for s in server.shares)
        raise PathError(
            "share_not_allowed",
            f"Share '{share_name}' is not allowed on '{server.alias}'. "
            f"Allowed: {allowed}.",
        )

    clean = []
    for seg in segments:
        if seg in ("..", ".") or seg.strip() != seg or seg.endswith("."):
            # "." / ".." traversal; trailing dot/space are normalised away by Windows
            # and are a classic filter-bypass trick.
            if seg == ".":
                continue
            raise PathError(
                "invalid_path", "Path traversal or invalid segment is not allowed."
            )
        if _INVALID_CHARS.search(seg):
            raise PathError("invalid_path", f"Invalid characters in '{seg}'.")
        clean.append(seg)

    return SmbTarget(
        server=server, share=share.name, rel="\\".join(clean), read_only=share.read_only
    )
