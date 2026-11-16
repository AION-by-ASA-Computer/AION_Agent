"""Path parsing and sandboxing for SMB targets.

Turns whatever the agent passes (``server/Share/sub/file.txt`` or the UNC form
``\\\\host\\Share\\sub\\file.txt``) into a canonical, validated target.  This is
the single gate that enforces the admin allowlist: unknown servers, unknown
shares, system shares (``C$``, ``ADMIN$``, ``IPC$``...), paths outside a
share's personal folder and ``..`` traversal are rejected *before* any
network call.

Hidden shares that are *not* system shares (``home$``, ``utenti$``) are
allowed: companies commonly use them for personal folders.  A share can carry
a ``folder`` template (e.g. ``{user}``) that confines every path on it to the
calling user's own sub-folder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional

from src.tools.smb_files.settings_store import SmbConfig, SmbServer, SmbShare

# Characters Windows forbids in file names (path separators handled separately).
_INVALID_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')

# Shares Windows creates on its own: whole disks (``C$``), remote admin
# (``ADMIN$``), IPC and printer drivers.  Never reachable, even if listed,
# because they expose far more than any business folder.  Other ``*$`` shares
# are just hidden from browsing and are allowed (e.g. ``home$``).
_SYSTEM_SHARE = re.compile(
    r"^(?:[A-Za-z]\$|ADMIN\$|IPC\$|PRINT\$|FAX\$)$", re.IGNORECASE
)

# Placeholder replaced with the calling user's account name in ``folder``.
USER_PLACEHOLDER = "{user}"

# Callback giving the Windows username (credentials of the server's set) used
# to fill ``{user}``; supplied by ops so this module stays credential-free.
UserLookup = Callable[[SmbServer], str]


def is_system_share(name: str) -> bool:
    """True for Windows system shares (``C$``, ``ADMIN$``, ``IPC$``...)."""
    return bool(_SYSTEM_SHARE.match((name or "").strip()))


def account_name(username: str) -> str:
    """Bare account name of ``DOM\\user`` / ``user@dom`` / ``user`` (for ``{user}``)."""
    name = (username or "").strip()
    if "\\" in name:
        name = name.split("\\", 1)[1]
    if "@" in name:
        name = name.rsplit("@", 1)[0]
    return name.strip()


def folder_segments(template: str) -> List[str]:
    """Split a ``folder`` template into segments or raise ``ValueError``.

    Used both by the admin API (validation on save) and at runtime.  Only
    ``{user}`` may appear as a placeholder; ``..`` and Windows-invalid
    characters are refused so the template can never escape the share.
    """
    parts = [p.strip() for p in (template or "").replace("/", "\\").split("\\")]
    parts = [p for p in parts if p]
    for seg in parts:
        literal = seg.replace(USER_PLACEHOLDER, "x")
        if seg in (".", "..") or seg.endswith(".") or "{" in literal or "}" in literal:
            raise ValueError(f"invalid folder segment '{seg}'")
        if _INVALID_CHARS.search(literal):
            raise ValueError(f"invalid characters in '{seg}'")
    return parts


def personal_root(share: SmbShare, username: str) -> List[str]:
    """Segments of the user's folder on ``share`` (``[]`` = whole share).

    Raises :class:`PathError` when the template needs a username that is not
    available or that would produce an unsafe segment.
    """
    if not share.folder:
        return []
    user = account_name(username)
    if USER_PLACEHOLDER in share.folder and (
        not user or user in (".", "..") or _INVALID_CHARS.search(user) or "/" in user
    ):
        raise PathError(
            "invalid_path", "Cannot determine the personal folder for this user."
        )
    return [
        seg.replace(USER_PLACEHOLDER, user) for seg in folder_segments(share.folder)
    ]


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


def resolve_path(
    raw: str, cfg: SmbConfig, user_lookup: Optional[UserLookup] = None
) -> SmbTarget:
    """Validate ``raw`` against ``cfg`` and return the canonical target.

    The first segment names the server: its alias (``fs01/Docs/a.txt``) or,
    in UNC form, its host (``\\\\fs01.corp.local\\Docs\\a.txt``).  Raises
    :class:`PathError` (``invalid_path``, ``server_not_allowed``,
    ``share_not_allowed``, ``outside_personal_folder``).

    ``user_lookup`` is needed only for shares with a ``folder`` template: it
    returns the Windows username for the server (may raise
    ``CredentialsMissing``).  Without it such shares are refused.
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
    # System shares are never reachable, even if an admin listed one.
    if is_system_share(share_name):
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

    # Personal-folder shares: every path must stay inside the user's folder,
    # so a misconfigured ACL on a colleague's folder is never reachable via AION.
    if share.folder:
        if user_lookup is None:
            raise PathError("share_not_allowed", "Personal folder not available.")
        root = personal_root(share, user_lookup(server))
        if [c.lower() for c in clean[: len(root)]] != [r.lower() for r in root]:
            mine = "/".join([server.alias, share.name, *root])
            raise PathError(
                "outside_personal_folder",
                f"On this share you can only access your personal folder: '{mine}'.",
            )

    return SmbTarget(
        server=server, share=share.name, rel="\\".join(clean), read_only=share.read_only
    )
