"""Per-tenant admin configuration of the SMB file server (read side).

Used by the ``smb_files`` MCP server to know which host and shares the admin
allowed.  Mirrors :mod:`src.notifications.smtp_settings`: a short TTL cache so
an admin save takes effect quickly without a DB hit on every tool call.
No secret is stored here: user credentials come from the per-user credential
store (env at spawn time).

The ORM model ``SmbSettings`` ships with the admin phase; until it exists
``_load_row`` returns ``None`` and the connector reports ``not_configured``.
Write-side helpers (upsert, public view, test result) live with the model.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aion.smb_files.settings")

AUTH_PROTOCOLS = ("ntlm", "negotiate")
CACHE_TTL = 30.0  # seconds: how long an admin change may take to be visible
DEFAULT_LOCKOUT_MINUTES = 30

_CACHE: Dict[str, Tuple[float, Optional["SmbConfig"]]] = {}


@dataclass(frozen=True)
class SmbShare:
    """A share the admin allowed; ``read_only`` blocks every write on it."""

    name: str
    read_only: bool = False
    label: str = ""


@dataclass(frozen=True)
class SmbConfig:
    """Resolved, usable admin configuration for one tenant."""

    host: str
    port: int = 445
    default_domain: str = ""
    shares: Tuple[SmbShare, ...] = field(default_factory=tuple)
    auth_protocol: str = "ntlm"  # "negotiate" prepares Kerberos support
    require_encryption: bool = False
    max_read_mb: int = 25
    max_write_mb: int = 25
    lockout_minutes: int = DEFAULT_LOCKOUT_MINUTES

    def share(self, name: str) -> Optional[SmbShare]:
        """Case-insensitive lookup (Windows share names are case-insensitive)."""
        low = (name or "").lower()
        return next((s for s in self.shares if s.name.lower() == low), None)


def invalidate_cache(tenant_id: str) -> None:
    """Drop the cached config; called by the admin API after a save."""
    _CACHE.pop(tenant_id, None)


async def _load_row(tenant_id: str) -> Any:
    """Fetch the ``smb_settings`` row, or ``None`` if model/row is missing."""
    try:
        from src.data.models import SmbSettings  # type: ignore[attr-defined]
    except ImportError:
        return None
    from src.data.engine import get_async_session_maker

    async with get_async_session_maker()() as session:
        return await session.get(SmbSettings, tenant_id)


def _parse_shares(raw: Any) -> Tuple[SmbShare, ...]:
    """Parse ``shares_json`` (list of dicts, possibly still a JSON string)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            return ()
    out: List[SmbShare] = []
    for item in raw or []:
        name = str((item or {}).get("name") or "").strip().strip("\\/")
        if name:
            out.append(
                SmbShare(
                    name=name,
                    read_only=bool(item.get("read_only")),
                    label=str(item.get("label") or ""),
                )
            )
    return tuple(out)


def _config_from_row(row: Any) -> Optional[SmbConfig]:
    """Build a config only for an enabled row with a host and >=1 share."""
    if row is None or not getattr(row, "enabled", False):
        return None
    host = (getattr(row, "host", "") or "").strip()
    shares = _parse_shares(getattr(row, "shares_json", None))
    if not host or not shares:
        return None
    proto = getattr(row, "auth_protocol", None) or "ntlm"
    return SmbConfig(
        host=host,
        port=int(getattr(row, "port", None) or 445),
        default_domain=(getattr(row, "default_domain", "") or "").strip(),
        shares=shares,
        auth_protocol=proto if proto in AUTH_PROTOCOLS else "ntlm",
        require_encryption=bool(getattr(row, "require_encryption", False)),
        max_read_mb=int(getattr(row, "max_read_mb", None) or 25),
        max_write_mb=int(getattr(row, "max_write_mb", None) or 25),
    )


async def get_smb_config(tenant_id: str) -> Optional[SmbConfig]:
    """Usable config for the tenant, or ``None`` if absent/disabled."""
    now = time.time()
    cached = _CACHE.get(tenant_id)
    if cached and now < cached[0]:
        return cached[1]
    cfg = _config_from_row(await _load_row(tenant_id))
    _CACHE[tenant_id] = (now + CACHE_TTL, cfg)
    return cfg
