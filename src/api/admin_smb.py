"""Admin API: Windows file server (SMB) used by the ``smb_files`` MCP connector.

Prefix ``/admin/smb``, admin role required.  The admin configures once per
tenant the host, the allowed shares (each optionally read-only) and the limits;
users only enter their own Windows credentials in chat-ui.  Nothing secret is
stored: the optional credentials of ``POST /test`` are used for that single
test and never saved, logged or audited.

Used by admin-ui (Settings -> File server, ``SmbSection.tsx``).  The MCP
workers read the saved row through ``src/tools/smb_files/settings_store.py``.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.data.audit import record_admin_action
from src.tools.smb_files import probe
from src.tools.smb_files.paths import _INVALID_CHARS
from src.tools.smb_files.settings_store import (
    AUTH_PROTOCOLS,
    get_smb_config_for_test,
    get_smb_settings_public,
    record_test_result,
    sync_connector_enabled,
    upsert_smb_settings,
)

logger = logging.getLogger("aion.api.admin_smb")
router = APIRouter(prefix="/admin/smb", tags=["admin_smb"])

MAX_SHARES = 50  # an allowlist, not an enumeration: more means misconfiguration


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


class SmbShareBody(BaseModel):
    """One allowed share; ``read_only`` blocks every write tool on it."""

    name: str = Field(..., max_length=80)
    read_only: bool = False
    label: Optional[str] = Field(None, max_length=128)


class SmbSettingsBody(BaseModel):
    enabled: bool = False
    host: str = Field("", max_length=256)
    port: int = Field(445, ge=1, le=65535)
    default_domain: Optional[str] = Field(None, max_length=128)
    shares: List[SmbShareBody] = Field(default_factory=list)
    auth_protocol: str = "ntlm"
    require_encryption: bool = False
    max_read_mb: int = Field(25, ge=1, le=500)
    max_write_mb: int = Field(25, ge=1, le=500)
    # Below 5 minutes the local block would expire before AD's own lockout.
    lockout_minutes: int = Field(30, ge=5, le=1440)


class SmbTestBody(BaseModel):
    """Optional credentials for this test only (never stored or logged)."""

    username: Optional[str] = Field(None, max_length=256)
    password: Optional[str] = Field(None, max_length=1024)


def _bad(code: str) -> HTTPException:
    return HTTPException(400, detail={"code": code})


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


@router.get("")
async def get_smb(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    return await get_smb_settings_public(_tenant_id())


@router.put("")
async def put_smb(
    body: SmbSettingsBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Save the configuration and mirror ``enabled`` on the Hub entry.

    A disabled row may be incomplete (draft); enabling requires a host and at
    least one share, otherwise users would get a connector that cannot work.
    """
    host = (body.host or "").strip()
    # Host name or IP only: a UNC/URL here would be ambiguous for path checks.
    if any(c.isspace() for c in host) or "\\" in host or "/" in host:
        raise _bad("invalid_host")
    domain = (body.default_domain or "").strip()
    if any(c.isspace() for c in domain) or "\\" in domain or "/" in domain:
        raise _bad("invalid_domain")
    auth_protocol = (body.auth_protocol or "").strip().lower()
    if auth_protocol not in AUTH_PROTOCOLS:
        raise _bad("invalid_auth_protocol")
    shares = _validate_shares(body.shares)
    if body.enabled and not host:
        raise _bad("invalid_host")
    if body.enabled and not shares:
        raise _bad("shares_required")

    tid = _tenant_id()
    await upsert_smb_settings(
        tid,
        enabled=body.enabled,
        host=host,
        port=body.port,
        default_domain=domain,
        shares=shares,
        auth_protocol=auth_protocol,
        require_encryption=body.require_encryption,
        max_read_mb=body.max_read_mb,
        max_write_mb=body.max_write_mb,
        lockout_minutes=body.lockout_minutes,
        actor_user_id=auth.user_row_id,
    )
    synced = await sync_connector_enabled(body.enabled)
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smb.update",
        resource_type="smb_settings",
        resource_id=tid,
        payload={
            "enabled": body.enabled,
            "host": host,
            "port": body.port,
            "shares": len(shares),
            "auth_protocol": auth_protocol,
            "require_encryption": body.require_encryption,
            "connector_synced": synced,
        },
    )
    logger.info("SMB settings updated by %s", auth.identifier)
    out = await get_smb_settings_public(tid)
    out["connector_synced"] = synced
    return out


@router.post("/test")
async def test_smb(
    body: SmbTestBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Test the saved configuration (also while disabled).

    Without credentials: negotiate only.  With credentials: logon + access to
    every share.  The credentials stay in this request: they are not saved,
    not logged and only ``with_credentials`` appears in the audit.
    """
    username = (body.username or "").strip()
    password = body.password or ""
    if bool(username) != bool(password):
        raise _bad("credentials_incomplete")

    tid = _tenant_id()
    cfg = await get_smb_config_for_test(tid)
    if cfg is None:
        raise HTTPException(409, detail={"code": "smb_not_configured"})

    result = await asyncio.to_thread(
        probe.test_connection, cfg, username or None, password or None
    )
    await record_test_result(tid, result.get("error"))
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smb.test",
        resource_type="smb_settings",
        resource_id=tid,
        payload={
            "ok": result.get("ok"),
            "error": result.get("error"),
            "with_credentials": bool(username),
        },
    )
    return result
