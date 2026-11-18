"""Filesystem layout and slug rules for customer-built MCP servers.

Layout (under the repository's ``mcp_servers/``, a host bind mount in every
Docker/GHCR deployment, so the code survives image upgrades)::

    mcp_servers/custom/
        <slug>/                  active version (code + aion-mcp.yaml)
        .staging/<upload_id>/    uploads being reviewed (src/ + upload.json)
        .versions/<slug>/<v>/    previous versions, for rollback
        .deps/<key>/             installed dependencies, shared by content hash of
                                 the requirements (mounted read-only at /deps)

``scripts/sync_mcp_servers.py`` never touches ``custom/`` (it only copies paths
that exist in ``mcp_servers_std/`` and skips this folder explicitly).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

# Folder name under mcp_servers/ that holds every custom server.
CUSTOM_DIR_NAME = "custom"

# Slug of a custom server: also its folder name and registry key. Lowercase so the
# per-user env prefix (AION_USER_<SLUG>__KEY) and folder names stay predictable.
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def repo_root() -> Path:
    """Repository root (``/app`` in the containers). Patched by tests."""
    return Path(__file__).resolve().parents[2]


def custom_root() -> Path:
    """``mcp_servers/custom/``: parent of every custom server folder."""
    return repo_root() / "mcp_servers" / CUSTOM_DIR_NAME


def staging_root() -> Path:
    """Where uploads wait for review before activation."""
    return custom_root() / ".staging"


def versions_root() -> Path:
    """Where previous versions of each custom server are archived."""
    return custom_root() / ".versions"


def deps_root() -> Path:
    """Where dependencies built by the verification step are stored."""
    return custom_root() / ".deps"


def server_dir(slug: str) -> Path:
    """Folder of the active version of a custom server."""
    return custom_root() / slug


def is_custom_config(config: Optional[Dict[str, Any]]) -> bool:
    """True when a registry entry was created by the custom upload flow.

    The ``aion_custom`` block is the marker every other module relies on to apply
    the custom-server rules (third-party env, manifest-owned credentials, locked
    command/args).
    """
    return isinstance(config, dict) and isinstance(config.get("aion_custom"), dict)


def slug_format_error(slug: str) -> Optional[str]:
    """Human-readable reason why ``slug`` is not a valid custom server slug."""
    if not SLUG_RE.match(slug or ""):
        return (
            "slug must be 3-41 characters: lowercase letters, digits and underscores, "
            "starting with a letter"
        )
    return None


def slug_conflict(slug: str) -> Optional[str]:
    """Reason why ``slug`` cannot be used by a custom server, or None when free.

    A custom server may reuse its own slug (that is an update), but never take the
    name of an AION server: the boot sync would overwrite std folders, and the
    registry/profile references would become ambiguous.
    """
    from ..mcp_manager import mcp_manager

    # Servers shipped with AION (std templates), even if not in the registry yet.
    if (repo_root() / "mcp_servers_std" / slug).exists():
        return f"'{slug}' is the name of an AION built-in server"
    # A non-custom folder already under mcp_servers/ (marketplace clone, manual copy).
    if (repo_root() / "mcp_servers" / slug).exists():
        return f"'{slug}' is already used by another server folder in mcp_servers/"
    mcp_manager.load_registry()
    if slug in mcp_manager._registry_base:
        return f"'{slug}' is the name of an AION built-in server"
    existing = mcp_manager._registry.get(slug)
    if existing is not None and not is_custom_config(existing):
        return f"'{slug}' is already used by an installed MCP server"
    return None
