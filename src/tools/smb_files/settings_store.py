"""Per-tenant admin configuration of the SMB file servers.

Two tables: ``smb_settings`` (one row per tenant: global switch and limits)
and ``smb_servers`` (one row per Windows file server, with its allowed shares
and the credential set its users authenticate with).

Read side: used by the ``smb_files`` MCP server to know which servers and
shares the admin allowed, and by the integrations API to build the per-set
credential fields (``src/runtime/dynamic_credential_fields.py``), with a short
TTL cache so an admin save takes effect quickly without a DB hit on every
tool call.
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
# Credential set backed by the historical SMB_USERNAME / SMB_PASSWORD keys.
DEFAULT_CREDENTIAL_SET = "DEFAULT"

_CACHE: Dict[str, Tuple[float, Optional["SmbConfig"]]] = {}


@dataclass(frozen=True)
class SmbShare:
    """A share the admin allowed; ``read_only`` blocks every write on it."""

    name: str
    read_only: bool = False
    label: str = ""


@dataclass(frozen=True)
class SmbServer:
    """One usable file server: the agent addresses it as ``<alias>/<Share>/...``."""

    alias: str
    host: str
    port: int = 445
    default_domain: str = ""
    # Servers in the same set (typically the same AD domain) share credentials.
    credential_set: str = DEFAULT_CREDENTIAL_SET
    shares: Tuple[SmbShare, ...] = field(default_factory=tuple)
    auth_protocol: str = "ntlm"  # "negotiate" prepares Kerberos support
    require_encryption: bool = False
    label: str = ""

    def share(self, name: str) -> Optional[SmbShare]:
        """Case-insensitive lookup (Windows share names are case-insensitive)."""
        low = (name or "").lower()
        return next((s for s in self.shares if s.name.lower() == low), None)


@dataclass(frozen=True)
class SmbConfig:
    """Resolved, usable admin configuration for one tenant."""

    servers: Tuple[SmbServer, ...] = field(default_factory=tuple)
    max_read_mb: int = 25
    max_write_mb: int = 25
    lockout_minutes: int = DEFAULT_LOCKOUT_MINUTES

    def server(self, alias: str) -> Optional[SmbServer]:
        """Lookup by alias (case-insensitive)."""
        low = (alias or "").lower()
        return next((s for s in self.servers if s.alias == low), None)

    def server_by_host(self, host: str) -> Optional[SmbServer]:
        """Lookup by host name, used for UNC paths (case-insensitive)."""
        low = (host or "").lower()
        return next((s for s in self.servers if s.host == low), None)

    def credential_sets(self) -> Dict[str, Tuple[str, ...]]:
        """Credential set -> aliases of the servers using it (admin order)."""
        out: Dict[str, List[str]] = {}
        for s in self.servers:
            out.setdefault(s.credential_set, []).append(s.alias)
        return {k: tuple(v) for k, v in out.items()}


def invalidate_cache(tenant_id: str) -> None:
    """Drop the cached config; called by the admin API after a save.

    Only affects the calling process: MCP workers keep their own cache and see
    the change within ``CACHE_TTL``.
    """
    _CACHE.pop(tenant_id, None)


async def _load_rows(tenant_id: str) -> Tuple[Any, List[Any]]:
    """Fetch the ``smb_settings`` row (or ``None``) and the tenant's servers."""
    # Imported lazily so ``import settings_store`` (MCP startup, list_tools)
    # does not pull in SQLAlchemy and the DB engine.
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import SmbServer as SmbServerRow
    from src.data.models import SmbSettings

    async with get_async_session_maker()() as session:
        settings = await session.get(SmbSettings, tenant_id)
        servers = (
            (
                await session.execute(
                    select(SmbServerRow)
                    .where(SmbServerRow.tenant_id == tenant_id)
                    .order_by(SmbServerRow.sort_order, SmbServerRow.alias)
                )
            )
            .scalars()
            .all()
        )
    return settings, list(servers)


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


def _server_from_row(row: Any) -> Optional[SmbServer]:
    """Build a server only for a row with a host and >=1 share (ignores ``enabled``)."""
    host = (getattr(row, "host", "") or "").strip().lower()
    alias = (getattr(row, "alias", "") or "").strip().lower()
    shares = _parse_shares(getattr(row, "shares_json", None))
    if not host or not alias or not shares:
        return None
    proto = getattr(row, "auth_protocol", None) or "ntlm"
    return SmbServer(
        alias=alias,
        host=host,
        port=int(getattr(row, "port", None) or 445),
        default_domain=(getattr(row, "default_domain", "") or "").strip(),
        credential_set=(
            getattr(row, "credential_set", None) or DEFAULT_CREDENTIAL_SET
        ).upper(),
        shares=shares,
        auth_protocol=proto if proto in AUTH_PROTOCOLS else "ntlm",
        require_encryption=bool(getattr(row, "require_encryption", False)),
        label=(getattr(row, "label", "") or "").strip(),
    )


def _config_from_rows(settings: Any, server_rows: List[Any]) -> Optional[SmbConfig]:
    """Usable config: global switch on and at least one enabled, complete server."""
    if settings is None or not getattr(settings, "enabled", False):
        return None
    servers = tuple(
        s
        for s in (_server_from_row(r) for r in server_rows if r.enabled)
        if s is not None
    )
    if not servers:
        return None
    return SmbConfig(
        servers=servers,
        max_read_mb=int(getattr(settings, "max_read_mb", None) or 25),
        max_write_mb=int(getattr(settings, "max_write_mb", None) or 25),
        lockout_minutes=int(
            getattr(settings, "lockout_minutes", None) or DEFAULT_LOCKOUT_MINUTES
        ),
    )


async def get_smb_config(tenant_id: str) -> Optional[SmbConfig]:
    """Usable config for the tenant, or ``None`` if absent/disabled."""
    now = time.time()
    cached = _CACHE.get(tenant_id)
    if cached and now < cached[0]:
        return cached[1]
    cfg = _config_from_rows(*await _load_rows(tenant_id))
    _CACHE[tenant_id] = (now + CACHE_TTL, cfg)
    return cfg


# --------------------------------------------------------------------------- admin


async def get_server_for_test(tenant_id: str, server_id: str) -> Optional[SmbServer]:
    """Server for the admin connection test: ignores both switches, no cache.

    The admin can verify a server before turning it (or the connector) on.
    """
    from src.data.engine import get_async_session_maker
    from src.data.models import SmbServer as SmbServerRow

    async with get_async_session_maker()() as session:
        row = await session.get(SmbServerRow, server_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return _server_from_row(row)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _server_public(row: Any) -> Dict[str, Any]:
    """Admin view of one server row; ``configured`` = host + alias + >=1 share."""
    return {
        "id": row.id,
        "configured": _server_from_row(row) is not None,
        "enabled": bool(row.enabled),
        "alias": row.alias,
        "label": row.label or "",
        "host": row.host or "",
        "port": int(row.port or 445),
        "default_domain": row.default_domain or "",
        "credential_set": row.credential_set or DEFAULT_CREDENTIAL_SET,
        "shares": [
            {"name": s.name, "read_only": s.read_only, "label": s.label}
            for s in _parse_shares(row.shares_json)
        ],
        "auth_protocol": row.auth_protocol or "ntlm",
        "require_encryption": bool(row.require_encryption),
        "last_test_at": _iso(row.last_test_at),
        "last_test_ok": row.last_test_ok,
        "last_test_error": row.last_test_error,
        "updated_at": _iso(row.updated_at),
    }


async def get_smb_settings_public(tenant_id: str) -> Dict[str, Any]:
    """Admin view: global settings (defaults if none yet) plus every server.

    ``configured`` tells admin-ui whether at least one enabled server is
    complete enough for the connector to work, independently of ``enabled``.
    """
    settings, rows = await _load_rows(tenant_id)
    servers = [_server_public(r) for r in rows]
    return {
        "configured": any(s["configured"] and s["enabled"] for s in servers),
        "enabled": bool(settings.enabled) if settings else False,
        "max_read_mb": int(settings.max_read_mb or 25) if settings else 25,
        "max_write_mb": int(settings.max_write_mb or 25) if settings else 25,
        "lockout_minutes": (
            int(settings.lockout_minutes or DEFAULT_LOCKOUT_MINUTES)
            if settings
            else DEFAULT_LOCKOUT_MINUTES
        ),
        "updated_at": _iso(settings.updated_at) if settings else None,
        "servers": servers,
    }


async def upsert_smb_global(
    tenant_id: str,
    *,
    enabled: bool,
    max_read_mb: int,
    max_write_mb: int,
    lockout_minutes: int,
    actor_user_id: Optional[str],
) -> None:
    """Create or update the tenant's global row; values already validated by the API."""
    from src.data.engine import get_async_session_maker
    from src.data.models import SmbSettings

    async with get_async_session_maker()() as session:
        row = await session.get(SmbSettings, tenant_id)
        if row is None:
            row = SmbSettings(tenant_id=tenant_id)
            session.add(row)
        row.enabled = enabled
        row.max_read_mb = max_read_mb
        row.max_write_mb = max_write_mb
        row.lockout_minutes = lockout_minutes
        row.updated_by_user_id = actor_user_id
        await session.commit()
    invalidate_cache(tenant_id)


async def find_server_conflict(
    tenant_id: str, *, alias: str, host: str, exclude_id: Optional[str] = None
) -> Optional[str]:
    """``duplicate_alias`` / ``duplicate_host`` if another server already uses them."""
    _, rows = await _load_rows(tenant_id)
    for r in rows:
        if r.id == exclude_id:
            continue
        if (r.alias or "").lower() == alias:
            return "duplicate_alias"
        if (r.host or "").lower() == host:
            return "duplicate_host"
    return None


async def count_servers(tenant_id: str) -> int:
    """Number of servers configured for the tenant (enforces the API cap)."""
    _, rows = await _load_rows(tenant_id)
    return len(rows)


def _apply_server_fields(row: Any, data: Dict[str, Any], actor: Optional[str]) -> None:
    """Copy validated API fields onto a row and reset its stale test result."""
    row.alias = data["alias"]
    row.label = data.get("label") or None
    row.host = data["host"]
    row.port = data["port"]
    row.default_domain = data.get("default_domain") or None
    row.credential_set = data["credential_set"]
    row.shares_json = json.dumps(data["shares"], ensure_ascii=False)
    row.auth_protocol = data["auth_protocol"]
    row.require_encryption = data["require_encryption"]
    row.enabled = data["enabled"]
    row.sort_order = data.get("sort_order", 0)
    # The configuration changed: the last test result no longer applies.
    row.last_test_at = None
    row.last_test_ok = None
    row.last_test_error = None
    row.updated_by_user_id = actor


async def create_smb_server(
    tenant_id: str, data: Dict[str, Any], actor_user_id: Optional[str]
) -> str:
    """Insert a server (fields validated by the API) and return its id."""
    from src.data.engine import get_async_session_maker
    from src.data.ids import new_uuid7_str
    from src.data.models import SmbServer as SmbServerRow

    # Kept aside: after commit the row is expired and detached from the session.
    server_id = new_uuid7_str()
    row = SmbServerRow(id=server_id, tenant_id=tenant_id)
    _apply_server_fields(row, data, actor_user_id)
    async with get_async_session_maker()() as session:
        session.add(row)
        await session.commit()
    invalidate_cache(tenant_id)
    return server_id


async def update_smb_server(
    tenant_id: str, server_id: str, data: Dict[str, Any], actor_user_id: Optional[str]
) -> bool:
    """Replace a server's fields; ``False`` if it does not belong to the tenant."""
    from src.data.engine import get_async_session_maker
    from src.data.models import SmbServer as SmbServerRow

    async with get_async_session_maker()() as session:
        row = await session.get(SmbServerRow, server_id)
        if row is None or row.tenant_id != tenant_id:
            return False
        _apply_server_fields(row, data, actor_user_id)
        await session.commit()
    invalidate_cache(tenant_id)
    return True


async def delete_smb_server(tenant_id: str, server_id: str) -> bool:
    """Remove a server's configuration (never touches files on the server)."""
    from src.data.engine import get_async_session_maker
    from src.data.models import SmbServer as SmbServerRow

    async with get_async_session_maker()() as session:
        row = await session.get(SmbServerRow, server_id)
        if row is None or row.tenant_id != tenant_id:
            return False
        await session.delete(row)
        await session.commit()
    invalidate_cache(tenant_id)
    return True


async def record_test_result(
    tenant_id: str, server_id: str, error_code: Optional[str]
) -> None:
    """Persist the outcome of the last admin connection test of one server."""
    from src.data.engine import get_async_session_maker
    from src.data.models import SmbServer as SmbServerRow

    async with get_async_session_maker()() as session:
        row = await session.get(SmbServerRow, server_id)
        if row is None or row.tenant_id != tenant_id:
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
