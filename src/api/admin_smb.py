"""Admin API: Windows file servers (SMB) used by the ``smb_files`` MCP connector.

Prefix ``/admin/smb``, admin role required.  The admin configures per tenant:

* the global switch and limits (``GET``/``PUT /admin/smb``);
* one or more file servers (``/admin/smb/servers``), each with a short alias
  (the agent writes paths as ``<alias>/<Share>/...``), its allowed shares
  (each optionally read-only) and the *credential set* its users log in with
  (servers of the same AD domain share a set; ``DEFAULT`` is the primary one).

Users only enter their own Windows credentials in chat-ui, one pair per set.
Nothing secret is stored here: the optional credentials of the connection
test are used for that single test and never saved, logged or audited.

Used by admin-ui (Settings -> File server, ``SmbSection.tsx``).  The MCP
workers read the saved rows through ``src/tools/smb_files/settings_store.py``.
"""

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.data.audit import record_admin_action
from src.tools.smb_files import probe
from src.tools.smb_files.paths import _INVALID_CHARS
from src.tools.smb_files.settings_store import (
    AUTH_PROTOCOLS,
    DEFAULT_CREDENTIAL_SET,
    count_servers,
    create_smb_server,
    delete_smb_server,
    find_server_conflict,
    get_server_for_test,
    get_smb_settings_public,
    record_test_result,
    sync_connector_enabled,
    update_smb_server,
    upsert_smb_global,
)

logger = logging.getLogger("aion.api.admin_smb")
router = APIRouter(prefix="/admin/smb", tags=["admin_smb"])

MAX_SHARES = 50  # an allowlist, not an enumeration: more means misconfiguration
MAX_SERVERS = 20  # per tenant; beyond this the agent's server list gets unwieldy
# First path segment of every agent path: short, lowercase, URL/path safe.
_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
# Becomes part of the credential keys (SMB_USERNAME__<SET>), hence the format.
_CRED_SET_RE = re.compile(r"^[A-Z0-9]{1,24}$")


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


class SmbShareBody(BaseModel):
    """One allowed share; ``read_only`` blocks every write tool on it."""

    name: str = Field(..., max_length=80)
    read_only: bool = False
    label: Optional[str] = Field(None, max_length=128)


class SmbGlobalBody(BaseModel):
    """Tenant-wide switch and limits (servers are managed separately)."""

    enabled: bool = False
    max_read_mb: int = Field(25, ge=1, le=500)
    max_write_mb: int = Field(25, ge=1, le=500)
    # Below 5 minutes the local block would expire before AD's own lockout.
    lockout_minutes: int = Field(30, ge=5, le=1440)


class SmbServerBody(BaseModel):
    """One file server; a disabled server may be an incomplete draft."""

    alias: str = Field(..., max_length=31)
    label: Optional[str] = Field(None, max_length=128)
    host: str = Field(..., max_length=256)
    port: int = Field(445, ge=1, le=65535)
    default_domain: Optional[str] = Field(None, max_length=128)
    credential_set: str = Field(DEFAULT_CREDENTIAL_SET, max_length=24)
    shares: List[SmbShareBody] = Field(default_factory=list)
    auth_protocol: str = "ntlm"
    require_encryption: bool = False
    enabled: bool = True
    sort_order: int = Field(0, ge=0, le=1000)


class SmbTestBody(BaseModel):
    """Optional credentials for this test only (never stored or logged)."""

    username: Optional[str] = Field(None, max_length=256)
    password: Optional[str] = Field(None, max_length=1024)


def _bad(code: str) -> HTTPException:
    return HTTPException(400, detail={"code": code})


def _clear_integrations_cache() -> None:
    """Refresh the users' "My integrations" form (per-set credential fields)."""
    # Imported lazily: the v1 router module pulls in much of the runtime.
    from src.api.v1.mcp_integrations import clear_integrations_cache

    clear_integrations_cache()


def _validate_shares(items: List[SmbShareBody]) -> List[Dict[str, Any]]:
    """Normalise the share allowlist or raise 400.

    Rejects administrative shares (``C$``, ``ADMIN$``, any ``*$``) so the agent
    can never be pointed at a whole disk, and sub-paths (``Share\\sub``)
    because the allowlist is per share, not per folder.
    """
    if len(items) > MAX_SHARES:
        raise _bad("too_many_shares")
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        name = (item.name or "").strip()
        if (
            not name
            or name in (".", "..")
            or name.endswith("$")
            or "\\" in name
            or "/" in name
            or _INVALID_CHARS.search(name)
        ):
            raise _bad("invalid_share_name")
        # Windows share names are case-insensitive.
        if name.lower() in seen:
            raise _bad("duplicate_share")
        seen.add(name.lower())
        out.append(
            {
                "name": name,
                "read_only": bool(item.read_only),
                "label": (item.label or "").strip(),
            }
        )
    return out


def _validate_server(body: SmbServerBody) -> Dict[str, Any]:
    """Normalise a server body into the ``settings_store`` field dict or raise 400."""
    alias = (body.alias or "").strip().lower()
    if not _ALIAS_RE.match(alias):
        raise _bad("invalid_alias")
    # Stored lowercase: smbclient caches sessions per host and UNC lookups
    # compare hosts case-insensitively.
    host = (body.host or "").strip().lower()
    # Host name or IP only: a UNC/URL here would be ambiguous for path checks.
    if not host or any(c.isspace() for c in host) or "\\" in host or "/" in host:
        raise _bad("invalid_host")
    domain = (body.default_domain or "").strip()
    if any(c.isspace() for c in domain) or "\\" in domain or "/" in domain:
        raise _bad("invalid_domain")
    cred_set = (body.credential_set or "").strip().upper() or DEFAULT_CREDENTIAL_SET
    if not _CRED_SET_RE.match(cred_set):
        raise _bad("invalid_credential_set")
    auth_protocol = (body.auth_protocol or "").strip().lower()
    if auth_protocol not in AUTH_PROTOCOLS:
        raise _bad("invalid_auth_protocol")
    shares = _validate_shares(body.shares)
    if body.enabled and not shares:
        raise _bad("shares_required")
    return {
        "alias": alias,
        "label": (body.label or "").strip(),
        "host": host,
        "port": body.port,
        "default_domain": domain,
        "credential_set": cred_set,
        "shares": shares,
        "auth_protocol": auth_protocol,
        "require_encryption": body.require_encryption,
        "enabled": body.enabled,
        "sort_order": body.sort_order,
    }


def _enabled_invariant_error(servers: List[Dict[str, Any]]) -> Optional[str]:
    """Why ``servers`` cannot back an enabled connector, or ``None``.

    Needs at least one enabled, complete server; and one of them must use the
    ``DEFAULT`` set, because the connector's required credentials (the ones
    that gate the MCP spawn and ``is_configured``) are the DEFAULT pair.
    """
    usable = [s for s in servers if s.get("enabled") and s.get("shares")]
    if not usable:
        return "servers_required"
    if not any(s.get("credential_set") == DEFAULT_CREDENTIAL_SET for s in usable):
        return "default_credential_set_required"
    return None


async def _check_change_keeps_connector_usable(
    tid: str, *, replace_id: Optional[str], new: Optional[Dict[str, Any]]
) -> None:
    """Reject (409) a server change that would break an enabled connector.

    ``replace_id`` + ``new``: update; ``replace_id`` only: delete; ``new``
    only: create.  No-op while the connector is globally disabled.
    """
    current = await get_smb_settings_public(tid)
    if not current["enabled"]:
        return
    servers = [s for s in current["servers"] if s["id"] != replace_id]
    if new is not None:
        servers.append(new)
    err = _enabled_invariant_error(servers)
    if err:
        raise HTTPException(409, detail={"code": err})


async def _server_exists(tid: str, server_id: str) -> Dict[str, Any]:
    """Public view of the server or 404 (also hides other tenants' ids)."""
    current = await get_smb_settings_public(tid)
    for s in current["servers"]:
        if s["id"] == server_id:
            return s
    raise HTTPException(404, detail={"code": "server_not_found"})


@router.get("")
async def get_smb(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Global settings plus every server (with its last test result)."""
    return await get_smb_settings_public(_tenant_id())


@router.put("")
async def put_smb(
    body: SmbGlobalBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Save the global settings and mirror ``enabled`` on the Hub entry.

    Enabling requires a usable server set (see :func:`_enabled_invariant_error`),
    otherwise users would get a connector that cannot work.
    """
    tid = _tenant_id()
    if body.enabled:
        current = await get_smb_settings_public(tid)
        err = _enabled_invariant_error(current["servers"])
        if err:
            raise _bad(err)

    await upsert_smb_global(
        tid,
        enabled=body.enabled,
        max_read_mb=body.max_read_mb,
        max_write_mb=body.max_write_mb,
        lockout_minutes=body.lockout_minutes,
        actor_user_id=auth.user_row_id,
    )
    synced = await sync_connector_enabled(body.enabled)
    _clear_integrations_cache()
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smb.update",
        resource_type="smb_settings",
        resource_id=tid,
        payload={
            "enabled": body.enabled,
            "max_read_mb": body.max_read_mb,
            "max_write_mb": body.max_write_mb,
            "lockout_minutes": body.lockout_minutes,
            "connector_synced": synced,
        },
    )
    logger.info("SMB settings updated by %s", auth.identifier)
    out = await get_smb_settings_public(tid)
    out["connector_synced"] = synced
    return out


def _audit_server_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Audit view of a server: configuration only (there is nothing secret)."""
    return {
        "alias": data["alias"],
        "host": data["host"],
        "port": data["port"],
        "credential_set": data["credential_set"],
        "shares": len(data["shares"]),
        "auth_protocol": data["auth_protocol"],
        "require_encryption": data["require_encryption"],
        "enabled": data["enabled"],
    }


@router.post("/servers")
async def create_server(
    body: SmbServerBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Add a file server; returns the full settings with the new server's id."""
    tid = _tenant_id()
    data = _validate_server(body)
    if await count_servers(tid) >= MAX_SERVERS:
        raise _bad("too_many_servers")
    conflict = await find_server_conflict(tid, alias=data["alias"], host=data["host"])
    if conflict:
        raise HTTPException(409, detail={"code": conflict})

    server_id = await create_smb_server(tid, data, auth.user_row_id)
    _clear_integrations_cache()
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smb.server.create",
        resource_type="smb_server",
        resource_id=server_id,
        payload=_audit_server_payload(data),
    )
    out = await get_smb_settings_public(tid)
    out["server_id"] = server_id
    return out


@router.put("/servers/{server_id}")
async def update_server(
    server_id: str,
    body: SmbServerBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Replace a server's configuration (resets its last test result)."""
    tid = _tenant_id()
    data = _validate_server(body)
    await _server_exists(tid, server_id)
    conflict = await find_server_conflict(
        tid, alias=data["alias"], host=data["host"], exclude_id=server_id
    )
    if conflict:
        raise HTTPException(409, detail={"code": conflict})
    await _check_change_keeps_connector_usable(tid, replace_id=server_id, new=data)

    if not await update_smb_server(tid, server_id, data, auth.user_row_id):
        raise HTTPException(404, detail={"code": "server_not_found"})
    _clear_integrations_cache()
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smb.server.update",
        resource_type="smb_server",
        resource_id=server_id,
        payload=_audit_server_payload(data),
    )
    return await get_smb_settings_public(tid)


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: str,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Remove a server's configuration only: no file on the server is touched."""
    tid = _tenant_id()
    existing = await _server_exists(tid, server_id)
    await _check_change_keeps_connector_usable(tid, replace_id=server_id, new=None)

    if not await delete_smb_server(tid, server_id):
        raise HTTPException(404, detail={"code": "server_not_found"})
    _clear_integrations_cache()
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smb.server.delete",
        resource_type="smb_server",
        resource_id=server_id,
        payload={"alias": existing["alias"], "host": existing["host"]},
    )
    return await get_smb_settings_public(tid)


@router.post("/servers/{server_id}/test")
async def test_server(
    server_id: str,
    body: SmbTestBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Test one saved server (also while it or the connector is disabled).

    Without credentials: negotiate only.  With credentials: logon + access to
    every share of that server.  The credentials stay in this request: they
    are not saved, not logged and only ``with_credentials`` appears in the
    audit.
    """
    username = (body.username or "").strip()
    password = body.password or ""
    if bool(username) != bool(password):
        raise _bad("credentials_incomplete")

    tid = _tenant_id()
    existing = await _server_exists(tid, server_id)
    server = await get_server_for_test(tid, server_id)
    if server is None:
        # Exists but incomplete (no share yet): nothing meaningful to test.
        raise HTTPException(409, detail={"code": "smb_not_configured"})

    result = await asyncio.to_thread(
        probe.test_connection, server, username or None, password or None
    )
    await record_test_result(tid, server_id, result.get("error"))
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smb.server.test",
        resource_type="smb_server",
        resource_id=server_id,
        payload={
            "alias": existing["alias"],
            "ok": result.get("ok"),
            "error": result.get("error"),
            "with_credentials": bool(username),
        },
    )
    return result
