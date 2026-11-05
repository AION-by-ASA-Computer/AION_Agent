"""Per-tenant admin configuration of the SMB file server (table ``smb_settings``).

Read side: used by the ``smb_files`` MCP server to know which host and shares
the admin allowed, with a short TTL cache so an admin save takes effect quickly
without a DB hit on every tool call.
Write side: used by the admin API (``src/api/admin_smb.py``) to save the
configuration, expose it to admin-ui, record test results and keep the Hub
entry of the connector in sync.  Mirrors :mod:`src.notifications.smtp_settings`.

No secret is stored here: user credentials come from the per-user credential
store (env at spawn time).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aion.smb_files.settings")

AUTH_PROTOCOLS = ("ntlm", "negotiate")
CONNECTOR_SLUG = "smb_files"  # server_slug of the registry / Hub entry
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
    """Drop the cached config; called by the admin API after a save.

    Only affects the calling process: MCP workers keep their own cache and see
    the change within ``CACHE_TTL``.
    """
    _CACHE.pop(tenant_id, None)


async def _load_row(tenant_id: str) -> Any:
    """Fetch the ``smb_settings`` row, or ``None`` if the tenant has none."""
    # Imported lazily so ``import settings_store`` (MCP startup, list_tools)
    # does not pull in SQLAlchemy and the DB engine.
    from src.data.engine import get_async_session_maker
    from src.data.models import SmbSettings

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


def _config_from_row(row: Any, require_enabled: bool = True) -> Optional[SmbConfig]:
    """Build a config only for a row with a host and >=1 share.

    ``require_enabled=False`` is used by the admin connection test, so the
    admin can verify the server before turning the connector on.
    """
    if row is None or (require_enabled and not getattr(row, "enabled", False)):
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
        lockout_minutes=int(
            getattr(row, "lockout_minutes", None) or DEFAULT_LOCKOUT_MINUTES
        ),
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


# --------------------------------------------------------------------------- admin


async def get_smb_config_for_test(tenant_id: str) -> Optional[SmbConfig]:
    """Config for the admin connection test: ignores ``enabled``, no cache."""
    return _config_from_row(await _load_row(tenant_id), require_enabled=False)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _shares_public(shares: Tuple[SmbShare, ...]) -> List[Dict[str, Any]]:
    return [
        {"name": s.name, "read_only": s.read_only, "label": s.label} for s in shares
    ]


async def get_smb_settings_public(tenant_id: str) -> Dict[str, Any]:
    """Admin view of the row (defaults when the tenant has none yet).

    ``configured`` tells admin-ui whether host and shares are enough for the
    connector to work, independently of the ``enabled`` switch.
    """
    row = await _load_row(tenant_id)
    if row is None:
        return {
            "configured": False,
            "enabled": False,
            "host": "",
            "port": 445,
            "default_domain": "",
            "shares": [],
            "auth_protocol": "ntlm",
            "require_encryption": False,
            "max_read_mb": 25,
            "max_write_mb": 25,
            "lockout_minutes": DEFAULT_LOCKOUT_MINUTES,
            "last_test_at": None,
            "last_test_ok": None,
            "last_test_error": None,
            "updated_at": None,
        }
    return {
        "configured": _config_from_row(row, require_enabled=False) is not None,
        "enabled": bool(row.enabled),
        "host": row.host or "",
        "port": int(row.port or 445),
        "default_domain": row.default_domain or "",
        "shares": _shares_public(_parse_shares(row.shares_json)),
        "auth_protocol": row.auth_protocol or "ntlm",
        "require_encryption": bool(row.require_encryption),
        "max_read_mb": int(row.max_read_mb or 25),
        "max_write_mb": int(row.max_write_mb or 25),
        "lockout_minutes": int(row.lockout_minutes or DEFAULT_LOCKOUT_MINUTES),
        "last_test_at": _iso(row.last_test_at),
        "last_test_ok": row.last_test_ok,
        "last_test_error": row.last_test_error,
        "updated_at": _iso(row.updated_at),
    }


async def upsert_smb_settings(
    tenant_id: str,
    *,
    enabled: bool,
    host: str,
    port: int,
    default_domain: str,
    shares: List[Dict[str, Any]],
    auth_protocol: str,
    require_encryption: bool,
    max_read_mb: int,
    max_write_mb: int,
    lockout_minutes: int,
    actor_user_id: Optional[str],
) -> None:
    """Create or update the tenant row; values are already validated by the API."""
    from src.data.engine import get_async_session_maker
    from src.data.models import SmbSettings

    async with get_async_session_maker()() as session:
        row = await session.get(SmbSettings, tenant_id)
        if row is None:
            row = SmbSettings(tenant_id=tenant_id)
            session.add(row)
        row.enabled = enabled
        row.host = host.strip() or None
        row.port = port
        row.default_domain = default_domain.strip() or None
        row.shares_json = json.dumps(shares, ensure_ascii=False)
        row.auth_protocol = auth_protocol
        row.require_encryption = require_encryption
        row.max_read_mb = max_read_mb
        row.max_write_mb = max_write_mb
        row.lockout_minutes = lockout_minutes
        # The configuration changed: the last test result no longer applies.
        row.last_test_at = None
        row.last_test_ok = None
        row.last_test_error = None
        row.updated_by_user_id = actor_user_id
        await session.commit()
    invalidate_cache(tenant_id)


async def record_test_result(tenant_id: str, error_code: Optional[str]) -> None:
    """Persist the outcome of the last admin connection test (no-op without row)."""
    from src.data.engine import get_async_session_maker
    from src.data.models import SmbSettings

    async with get_async_session_maker()() as session:
        row = await session.get(SmbSettings, tenant_id)
        if row is None:
            return
        row.last_test_at = datetime.now(timezone.utc)
        row.last_test_ok = error_code is None
        row.last_test_error = error_code
        await session.commit()


async def sync_connector_enabled(enabled: bool) -> bool:
    """Mirror the admin switch on the Hub entry of the connector.

    Sets ``McpServerConfig.is_enabled_for_users`` of ``smb_files`` so turning
    the file server on/off in Settings also exposes/hides it to users.  Returns
    ``False`` when the Hub row does not exist yet (registry not synced): the
    admin then enables the connector from the Hub as for any other server.
    """
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import McpServerConfig

    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == CONNECTOR_SLUG
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            logger.info("smb_files: no Hub entry yet, enabled flag not synced")
            return False
        if bool(row.is_enabled_for_users) != enabled:
            row.is_enabled_for_users = enabled
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
        return True
