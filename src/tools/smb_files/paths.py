"""Path parsing and sandboxing for SMB targets.

Turns whatever the agent passes (``Share/sub/file.txt`` or the UNC form
``\\\\host\\Share\\sub\\file.txt``) into a canonical, validated target.  This is
the single gate that enforces the admin allowlist: unknown shares,
administrative shares (``C$``, ``ADMIN$``, ``IPC$``...), other hosts and ``..``
traversal are rejected *before* any network call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.tools.smb_files.settings_store import SmbConfig

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

    host: str
    share: str
    rel: str  # path inside the share, backslash separated, "" = share root
    read_only: bool

    @property
    def unc(self) -> str:
        base = f"\\\\{self.host}\\{self.share}"
        return f"{base}\\{self.rel}" if self.rel else base

    @property
    def display(self) -> str:
        """Share-relative form shown back to the agent/user."""
        return f"{self.share}/{self.rel.replace(chr(92), '/')}".rstrip("/")


def resolve_path(raw: str, cfg: SmbConfig) -> SmbTarget:
    """Validate ``raw`` against ``cfg`` and return the canonical target.

    Raises :class:`PathError` (``invalid_path``, ``share_not_allowed``,
    ``host_not_allowed``).
    """
    text = (raw or "").strip()
    if not text:
        raise PathError("invalid_path", "Empty path.")
    norm = text.replace("/", "\\")
    host = cfg.host

    if norm.startswith("\\\\"):
        # UNC form: the host must be exactly the configured one.
        parts = [p for p in norm[2:].split("\\") if p != ""]
        if len(parts) < 2:
            raise PathError("invalid_path", "UNC path must include host and share.")
        if parts[0].lower() != cfg.host.lower():
            raise PathError(
                "host_not_allowed", "Only the configured file server is reachable."
            )
        parts = parts[1:]
    else:
        parts = [p for p in norm.split("\\") if p != ""]
    if not parts:
        raise PathError("invalid_path", "Path must start with a share name.")

    share_name, segments = parts[0], parts[1:]
    # Administrative/hidden shares are never reachable, even if an admin listed one.
    if share_name.endswith("$"):
        raise PathError(
            "share_not_allowed", "Administrative shares are not accessible."
        )
    share = cfg.share(share_name)
    if share is None:
        allowed = ", ".join(s.name for s in cfg.shares)
        raise PathError(
            "share_not_allowed",
            f"Share '{share_name}' is not allowed. Allowed: {allowed}.",
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
        host=host, share=share.name, rel="\\".join(clean), read_only=share.read_only
    )
