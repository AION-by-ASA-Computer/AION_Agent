"""Admin endpoints for network settings of the jails (``/admin/network``).

Backs the "Network" section of admin-ui Settings:

- ``GET /ca``: the company certificate authority in use (source, certificates,
  expiry), plus a summary of the jail network (engine, corporate proxy);
- ``PUT /ca``: upload the company CA (PEM or DER). It is validated, stored in the
  AION data volume and applied right away: running custom MCP servers are
  restarted so their next call trusts it. No ``.env`` edit, no container restart;
- ``DELETE /ca``: remove the uploaded CA (same immediate effect).

When ``AION_SANDBOX_CA_BUNDLE`` is set in ``.env`` it wins and the CA is read-only
here. Included by ``src/api/admin.py`` (inherits ``require_admin_role``); every
change is written to ``audit_log``. Logic: ``src/security/company_ca.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.security import company_ca

logger = logging.getLogger("aion.api.admin_network")

router = APIRouter(prefix="/network", tags=["admin-network"])


def _actor(auth: ChatAuthIdentity) -> str:
    return auth.identifier or auth.user_row_id or "admin"


async def _apply_to_running_servers() -> int:
    """Restart the workers of every custom MCP server so the new CA is used.

    The combined bundle is rebuilt by ``jail_ca_bundle`` at the next start of each
    server; returns how many servers were restarted.
    """
    from src.mcp_custom.ca import jail_ca_bundle
    from src.mcp_custom.install import invalidate_runtime
    from src.mcp_custom.paths import is_custom_config
    from src.mcp_manager import mcp_manager

    await asyncio.to_thread(jail_ca_bundle)  # write/remove the bundle now
    mcp_manager.load_registry()
    slugs = [s for s, cfg in mcp_manager._registry.items() if is_custom_config(cfg)]
    for slug in slugs:
        await invalidate_runtime(slug)
    return len(slugs)


async def _audit(actor: str, operation: str, payload: Dict[str, Any]) -> None:
    from src.data.audit import record_admin_action

    await record_admin_action(
        tenant_id=(os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip(),
        actor=actor,
        operation=operation,
        resource_type="network",
        resource_id="company_ca",
        payload=payload,
    )


def _network_summary() -> Dict[str, Any]:
    """Read-only facts about the jail network shown next to the CA.

    Which destinations each custom MCP server may reach is its own allowlist
    (MCP Hub -> Configure), so nothing installation-wide is listed here.
    """
    from src.security.container_runtime import get_container_runtime

    return {
        "container_runtime": get_container_runtime().runtime,
        "proxy": bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")),
    }


@router.get("/ca")
async def get_company_ca() -> Dict[str, Any]:
    """Company CA in use and the network summary."""
    state = await asyncio.to_thread(company_ca.describe_active)
    return {**state, "network": _network_summary()}


@router.put("/ca")
async def put_company_ca(
    file: UploadFile = File(...),
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Upload the company CA (PEM/DER); applied immediately to custom MCP servers."""
    if company_ca.env_override():
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ca_managed_by_env",
                "message": "The company CA is set by AION_SANDBOX_CA_BUNDLE in .env: change it there.",
            },
        )
    data = await file.read(company_ca.MAX_CA_BYTES + 1)
    try:
        result = await asyncio.to_thread(
            company_ca.save_uploaded_ca, data, filename=file.filename or "", actor=_actor(auth)
        )
    except company_ca.CompanyCAError as exc:
        raise HTTPException(status_code=400, detail={"error": "ca_invalid", "message": str(exc)}) from exc
    restarted = await _apply_to_running_servers()
    await _audit(
        _actor(auth),
        "network.company_ca.upload",
        {
            "filename": result.get("filename"),
            "subjects": [c["subject"] for c in result.get("certificates", [])],
            "servers_restarted": restarted,
        },
    )
    logger.info("Company CA uploaded by %s (%d certificates)", _actor(auth), len(result.get("certificates", [])))
    return {**result, "servers_restarted": restarted, "network": _network_summary()}


@router.delete("/ca")
async def delete_company_ca(auth: ChatAuthIdentity = Depends(require_admin_role)) -> Dict[str, Any]:
    """Remove the uploaded company CA; applied immediately."""
    if company_ca.env_override():
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ca_managed_by_env",
                "message": "The company CA is set by AION_SANDBOX_CA_BUNDLE in .env: remove it there.",
            },
        )
    removed = await asyncio.to_thread(company_ca.remove_uploaded_ca)
    restarted = await _apply_to_running_servers() if removed else 0
    if removed:
        await _audit(_actor(auth), "network.company_ca.delete", {"servers_restarted": restarted})
    return {"removed": removed, "servers_restarted": restarted}
